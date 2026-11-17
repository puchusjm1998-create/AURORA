"""Invoices: upload of originals, manual line capture and reconciliation.

OCR is a pluggable external service (Phase 4). Until a provider is configured,
``ocr_status`` is ``not_configured`` and the API never invents extracted data:
lines are entered and reviewed by a human.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import TypeAdapter, ValidationError as PydanticValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.api.serializers import invoice_to_read
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import InvoiceStatus, OCRStatus, PermissionCode
from app.core.timeutils import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Invoice,
    InvoiceExtraction,
    InvoiceLine,
    Product,
    StockMovement,
    Supplier,
    User,
)
from app.schemas import (
    InvoiceExtractionRead,
    InvoiceLineCreate,
    InvoiceLineRead,
    InvoiceOcrPreview,
    InvoiceRead,
    InvoiceUpdate,
    Message,
    Page,
)
from app.services.audit import record_audit
from app.services.ocr import confidence_score, engine_status, extract_document
from app.services.storage import ALLOWED_MIME, resolve_stored_path, store_invoice_file

router = APIRouter(prefix="/invoices", tags=["Facturas"])
settings = get_settings()


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _match_supplier(db: Session, parsed: dict):
    tax_id = parsed.get("supplier_tax_id")
    if tax_id:
        supplier = db.scalars(select(Supplier).where(Supplier.tax_id == tax_id)).first()
        if supplier:
            return supplier
    name = parsed.get("supplier_name")
    if name and len(name) >= 3:
        supplier = db.scalars(
            select(Supplier).where(Supplier.name.ilike(f"%{name[:40]}%"))
        ).first()
        if supplier:
            return supplier
    return None


def _preview_payload(result, db: Session) -> InvoiceOcrPreview:
    parsed = dict(result.parsed)
    supplier = _match_supplier(db, parsed)
    return InvoiceOcrPreview(
        status=result.status,
        engine=result.engine,
        method=result.method,
        confidence=confidence_score(parsed, result.confidence, result.method),
        page_count=result.page_count,
        raw_text=result.raw_text,
        matched_supplier_id=supplier.id if supplier else None,
        matched_supplier_name=supplier.name if supplier else None,
        warnings=result.warnings,
        **parsed,
    )


def _extraction_read(extraction: InvoiceExtraction) -> InvoiceExtractionRead:
    payload = dict(extraction.parsed or {})
    payload.pop("lines", None)
    return InvoiceExtractionRead(
        id=extraction.id,
        invoice_id=extraction.invoice_id,
        filename=extraction.filename,
        created_by=extraction.created_by,
        creator_name=extraction.creator.full_name if extraction.creator else None,
        created_at=extraction.created_at,
        status=extraction.status.value,
        engine=extraction.engine,
        method=extraction.method,
        confidence=float(extraction.confidence),
        page_count=extraction.page_count,
        raw_text=extraction.raw_text,
        lines=(extraction.parsed or {}).get("lines", []),
        warnings=extraction.warnings or [],
        **payload,
    )


def _recalculate(invoice: Invoice) -> None:
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line in invoice.lines:
        gross = line.quantity * line.unit_price * (1 - line.discount_pct / 100)
        line.line_total = _money(gross * (1 + line.tax_rate / 100))
        subtotal += _money(gross)
        tax_total += _money(gross * line.tax_rate / 100)
    invoice.subtotal = _money(subtotal)
    invoice.tax_total = _money(tax_total)
    invoice.total = _money(subtotal + tax_total)


@router.get("", response_model=Page[InvoiceRead], summary="Listar facturas")
def list_invoices(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVOICES_READ)),
    search: str | None = None,
    status: str | None = None,
    supplier_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[InvoiceRead]:
    stmt = select(Invoice)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(Invoice.number.ilike(term), Invoice.original_filename.ilike(term))
        )
    if status:
        stmt = stmt.where(Invoice.status == status)
    if supplier_id:
        stmt = stmt.where(Invoice.supplier_id == supplier_id)
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    invoices = list(
        db.scalars(
            stmt.order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return Page(items=[invoice_to_read(i) for i in invoices], total=total, limit=limit, offset=offset)


@router.post("", response_model=InvoiceRead, status_code=201, summary="Subir factura")
async def create_invoice(
    number: str = Form(..., min_length=1, max_length=80),
    invoice_date: date = Form(...),
    supplier_id: str | None = Form(None),
    notes: str = Form(""),
    lines_json: str | None = Form(None),
    ocr_reviewed: bool = Form(False),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVOICES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> InvoiceRead:
    supplier = db.get(Supplier, supplier_id) if supplier_id else None
    if supplier_id and supplier is None:
        raise NotFoundError("Proveedor", supplier_id)
    duplicate = db.scalars(
        select(Invoice).where(
            Invoice.supplier_id == supplier_id,
            Invoice.number == number.strip(),
        )
    ).first()
    if duplicate:
        raise ConflictError(f"Ya existe la factura {number} para este proveedor.")

    suggested_lines: list[InvoiceLineCreate] = []
    if lines_json:
        try:
            raw_lines = json.loads(lines_json)
            if not isinstance(raw_lines, list) or len(raw_lines) > 100:
                raise ValueError("se esperaba una lista de hasta 100 líneas")
            suggested_lines = TypeAdapter(list[InvoiceLineCreate]).validate_python(raw_lines)
        except (ValueError, json.JSONDecodeError, PydanticValidationError) as exc:
            raise ValidationError(
                "Las líneas revisadas no son válidas.", code="invalid_lines",
                details={"reason": str(exc)[:300]},
            ) from exc
        for line in suggested_lines:
            if line.product_id and db.get(Product, line.product_id) is None:
                raise NotFoundError("Producto", line.product_id)

    stored = None
    if file is not None:
        stored = await store_invoice_file(
            file,
            invoice_date=invoice_date,
            supplier=supplier.name if supplier else "SIN-PROVEEDOR",
            number=number,
        )
        if db.scalars(select(Invoice).where(Invoice.file_sha256 == stored.sha256)).first():
            raise ConflictError(
                "Ese documento ya fue cargado anteriormente.",
                code="duplicate_document",
            )

    invoice = Invoice(
        number=number.strip(),
        supplier_id=supplier_id,
        invoice_date=invoice_date,
        notes=notes,
        source="upload" if stored else "manual",
        ocr_status=(OCRStatus.DONE if ocr_reviewed else OCRStatus.NOT_CONFIGURED),
        uploaded_by=user.id,
        file_path=stored.relative_path if stored else None,
        original_filename=stored.original_filename if stored else None,
        mime_type=stored.mime_type if stored else None,
        file_sha256=stored.sha256 if stored else None,
    )
    db.add(invoice)
    db.flush()
    for index, payload in enumerate(suggested_lines, start=1):
        db.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_number=index,
                product_id=payload.product_id,
                supplier_ref=payload.supplier_ref,
                description=payload.description,
                quantity=payload.quantity,
                unit_price=payload.unit_price,
                discount_pct=payload.discount_pct,
                tax_rate=payload.tax_rate,
                line_total=Decimal("0"),
            )
        )
    if suggested_lines:
        db.flush()
        db.expire(invoice, ["lines"])
        _recalculate(invoice)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="invoice.created",
        entity_type="invoice",
        entity_id=invoice.id,
        after={
            "number": invoice.number,
            "supplier_id": supplier_id,
            "sha256": invoice.file_sha256,
            "ocr_status": invoice.ocr_status.value,
            "reviewed_lines": len(suggested_lines),
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(invoice)
    return invoice_to_read(invoice)


@router.get("/ocr/config", response_model=Message, summary="Estado del motor OCR")
def ocr_config(
    _: User = Depends(require_permission(PermissionCode.INVOICES_READ)),
) -> Message:
    status = engine_status()
    return Message(
        message=(
            "OCR local disponible: PDF con texto, PDF escaneado e imágenes."
            if status["available"]
            else "El motor OCR local no está disponible en este servidor."
        ),
        details=status,
    )


@router.post("/ocr/preview", response_model=InvoiceOcrPreview, summary="Extraer datos sin registrar")
async def ocr_preview(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVOICES_WRITE)),
) -> InvoiceOcrPreview:
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        raise ValidationError(
            "Formato no admitido. Suba un PDF, JPG, PNG, WEBP o TIFF.",
            code="unsupported_file_type",
        )
    limit = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise ValidationError(
            f"El archivo supera el límite de {settings.max_upload_mb} MB.", code="file_too_large"
        )
    if not content:
        raise ValidationError("El archivo está vacío.", code="empty_file")

    suffix = ALLOWED_MIME[mime]
    temporary = tempfile.NamedTemporaryFile(prefix="aurora-ocr-", suffix=suffix, delete=False)
    try:
        temporary.write(content)
        temporary.close()
        result = await run_in_threadpool(extract_document, Path(temporary.name), mime)
    finally:
        Path(temporary.name).unlink(missing_ok=True)
    preview = _preview_payload(result, db)
    preview.human_review_required = True
    return preview


@router.post(
    "/{invoice_id}/extract",
    response_model=InvoiceExtractionRead,
    summary="Extraer datos del documento guardado",
)
def extract_invoice(
    invoice_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVOICES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> InvoiceExtractionRead:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    if not invoice.file_path:
        raise ConflictError(
            "La factura no tiene documento original que procesar.", code="no_document"
        )
    path = resolve_stored_path(invoice.file_path)
    result = extract_document(path, invoice.mime_type or "application/pdf")
    extraction = InvoiceExtraction(
        invoice_id=invoice.id,
        filename=invoice.original_filename or path.name,
        mime_type=invoice.mime_type or "",
        sha256=invoice.file_sha256 or hashlib.sha256(path.read_bytes()).hexdigest(),
        engine=result.engine,
        method=result.method,
        status=OCRStatus.DONE if result.status == "done" else OCRStatus.FAILED,
        confidence=Decimal(str(round(result.confidence, 4))),
        page_count=result.page_count,
        raw_text=result.raw_text,
        parsed=_json_safe(result.parsed),
        warnings=result.warnings,
        created_by=user.id,
    )
    invoice.ocr_status = extraction.status
    db.add(extraction)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="invoice.ocr_completed",
        entity_type="invoice_extraction",
        entity_id=extraction.id,
        after={
            "invoice": invoice.number,
            "engine": result.engine,
            "method": result.method,
            "status": extraction.status.value,
            "confidence": str(extraction.confidence),
            "lines": len(result.parsed.get("lines", [])),
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(extraction)
    return _extraction_read(extraction)


@router.post(
    "/{invoice_id}/lines/bulk",
    response_model=InvoiceRead,
    summary="Añadir líneas revisadas en lote",
)
def add_invoice_lines_bulk(
    invoice_id: str,
    payload: list[InvoiceLineCreate],
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVOICES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> InvoiceRead:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    if invoice.status == InvoiceStatus.RECONCILED:
        raise ConflictError("La factura ya está conciliada; no admite nuevas líneas.")
    if not payload:
        raise ValidationError("No hay líneas que añadir.", code="empty_lines")
    if len(payload) > 100:
        raise ValidationError("Máximo 100 líneas por lote.", code="too_many_lines")
    for line in payload:
        if line.product_id and db.get(Product, line.product_id) is None:
            raise NotFoundError("Producto", line.product_id)
    next_line = max((line.line_number for line in invoice.lines), default=0) + 1
    for offset, line in enumerate(payload):
        db.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_number=next_line + offset,
                product_id=line.product_id,
                supplier_ref=line.supplier_ref,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_pct=line.discount_pct,
                tax_rate=line.tax_rate,
                line_total=Decimal("0"),
                review_required=True,
            )
        )
    db.flush()
    db.expire(invoice, ["lines"])
    _recalculate(invoice)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="invoice.lines_bulk_added",
        entity_type="invoice",
        entity_id=invoice.id,
        after={"invoice": invoice.number, "lines": len(payload), "source": "ocr_review"},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(invoice)
    return invoice_to_read(invoice)


@router.get("/{invoice_id}", response_model=InvoiceRead, summary="Consultar factura")
def get_invoice(
    invoice_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVOICES_READ)),
) -> InvoiceRead:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    return invoice_to_read(invoice)


@router.get("/{invoice_id}/file", summary="Descargar documento original")
def download_invoice_file(
    invoice_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVOICES_READ)),
) -> FileResponse:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or not invoice.file_path:
        raise NotFoundError("Documento original", invoice_id)
    path = resolve_stored_path(invoice.file_path)
    return FileResponse(
        path,
        media_type=invoice.mime_type or "application/octet-stream",
        filename=invoice.original_filename or path.name,
    )


@router.patch("/{invoice_id}", response_model=InvoiceRead, summary="Modificar cabecera")
def update_invoice(
    invoice_id: str,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVOICES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> InvoiceRead:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    changes = payload.model_dump(exclude_unset=True)
    if "supplier_id" in changes and changes["supplier_id"]:
        if db.get(Supplier, changes["supplier_id"]) is None:
            raise NotFoundError("Proveedor", changes["supplier_id"])
    for field, value in changes.items():
        setattr(invoice, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="invoice.updated",
        entity_type="invoice",
        entity_id=invoice.id,
        after=changes,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(invoice)
    return invoice_to_read(invoice)


@router.post("/{invoice_id}/lines", response_model=InvoiceLineRead, status_code=201, summary="Añadir línea")
def add_invoice_line(
    invoice_id: str,
    payload: InvoiceLineCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVOICES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> InvoiceLineRead:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    if invoice.status == InvoiceStatus.RECONCILED:
        raise ConflictError("La factura ya está conciliada; no admite nuevas líneas.")
    if payload.product_id and db.get(Product, payload.product_id) is None:
        raise NotFoundError("Producto", payload.product_id)

    next_line = max((line.line_number for line in invoice.lines), default=0) + 1
    line = InvoiceLine(
        invoice_id=invoice.id,
        line_number=next_line,
        product_id=payload.product_id,
        supplier_ref=payload.supplier_ref,
        description=payload.description,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        discount_pct=payload.discount_pct,
        tax_rate=payload.tax_rate,
        line_total=Decimal("0"),
    )
    db.add(line)
    db.flush()
    db.expire(invoice, ["lines"])
    _recalculate(invoice)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="invoice.line_added",
        entity_type="invoice_line",
        entity_id=line.id,
        after={
            "invoice": invoice.number,
            "line": next_line,
            "product_id": payload.product_id,
            "quantity": payload.quantity,
            "unit_price": payload.unit_price,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(line)
    return InvoiceLineRead(
        id=line.id,
        line_number=line.line_number,
        product_id=line.product_id,
        supplier_ref=line.supplier_ref,
        description=line.description,
        quantity=line.quantity,
        unit_price=line.unit_price,
        discount_pct=line.discount_pct,
        tax_rate=line.tax_rate,
        line_total=line.line_total,
        received_quantity=line.received_quantity,
        review_required=line.review_required,
        product_sku=line.product.sku if line.product else None,
        product_name=line.product.name if line.product else None,
    )


@router.delete("/{invoice_id}/lines/{line_id}", response_model=InvoiceRead, summary="Eliminar línea")
def delete_invoice_line(
    invoice_id: str,
    line_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVOICES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> InvoiceRead:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    line = db.get(InvoiceLine, line_id)
    if line is None or line.invoice_id != invoice.id:
        raise NotFoundError("Línea de factura", line_id)
    if line.received_quantity > 0:
        raise ConflictError("No puede eliminarse una línea con recepciones registradas.")
    db.delete(line)
    db.flush()
    db.expire(invoice, ["lines"])
    _recalculate(invoice)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="invoice.line_deleted",
        entity_type="invoice_line",
        entity_id=line_id,
        after={"invoice": invoice.number},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(invoice)
    return invoice_to_read(invoice)


@router.post("/{invoice_id}/reconcile", response_model=InvoiceRead, summary="Conciliar con recepciones")
def reconcile_invoice(
    invoice_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVOICES_RECONCILE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> InvoiceRead:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    if not invoice.lines:
        raise ValidationError("La factura no tiene líneas que conciliar.")

    discrepancies = 0
    for line in invoice.lines:
        received = db.scalar(
            select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
                StockMovement.invoice_line_id == line.id,
                StockMovement.status == "confirmed",
            )
        )
        line.received_quantity = Decimal(str(received or 0))
        if line.received_quantity != line.quantity:
            line.review_required = True
            discrepancies += 1
        else:
            line.review_required = False

    invoice.status = InvoiceStatus.DISCREPANCY if discrepancies else InvoiceStatus.RECONCILED
    invoice.reconciled_at = utcnow()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="invoice.reconciled",
        entity_type="invoice",
        entity_id=invoice.id,
        after={"status": invoice.status.value, "discrepancies": discrepancies},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(invoice)
    return invoice_to_read(invoice)


@router.get("/{invoice_id}/ocr-status", response_model=Message, summary="Estado del OCR")
def ocr_status(
    invoice_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVOICES_READ)),
) -> Message:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Factura", invoice_id)
    status = engine_status()
    return Message(
        message=(
            "OCR local disponible; procese el documento y revise los datos propuestos."
            if status["available"]
            else "El motor OCR local no está disponible en este servidor."
        ),
        details={
            "ocr_status": invoice.ocr_status.value,
            "provider_configured": status["available"],
            "engine": status["engine"],
            "external_service": False,
            "human_review_required": True,
        },
    )
