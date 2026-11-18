"""QR rendering and printable label data."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import NotFoundError, ValidationError
from app.models import Employee, Location, Pallet, Product, ProductUnit, User
from app.services.qr import QRKind, build_payload, parse_payload, render_png

router = APIRouter(prefix="/qr", tags=["Etiquetas QR"])


@router.get("", summary="Imagen PNG de un código QR AURORA")
def qr_image(
    payload: str = Query(..., description="Ej. aurora://pallet/AUR-PAL-000001"),
    box_size: int = Query(8, ge=3, le=20),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> Response:
    if parse_payload(payload) is None:
        raise ValidationError("El contenido debe ser un código AURORA válido (aurora://tipo/código).")
    png = render_png(payload, box_size=box_size)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/labels/{kind}/{entity_id}", summary="Datos de etiqueta imprimible")
def label_data(
    kind: str,
    entity_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> dict:
    if kind == "product":
        product = db.get(Product, entity_id)
        if product is None:
            raise NotFoundError("Producto", entity_id)
        payload = build_payload(QRKind.PRODUCT, product.sku)
        return {
            "payload": payload,
            "kind": "product",
            "title": product.name,
            "code": product.sku,
            "lines": [
                f"Ref. fabricante: {product.manufacturer_ref or '—'}",
                f"Ud.: {product.uom} · {product.category}",
            ],
        }
    if kind == "pallet":
        pallet = db.get(Pallet, entity_id)
        if pallet is None:
            raise NotFoundError("Palé", entity_id)
        payload = build_payload(QRKind.PALLET, pallet.code)
        return {
            "payload": payload,
            "kind": "pallet",
            "title": f"Palé {pallet.code}",
            "code": pallet.code,
            "lines": [
                f"Almacén: {pallet.warehouse.code}",
                f"Ubicación: {pallet.location.full_code if pallet.location else 'sin asignar'}",
                f"Contenido: {len(pallet.items)} referencias",
            ],
        }
    if kind == "unit":
        unit = db.get(ProductUnit, entity_id)
        if unit is None:
            raise NotFoundError("Unidad", entity_id)
        payload = build_payload(QRKind.UNIT, unit.code)
        return {
            "payload": payload,
            "kind": "unit",
            "title": unit.product.name,
            "code": unit.code,
            "lines": [
                f"SKU: {unit.product.sku}",
                f"Serie: {unit.serial_number or '—'}",
                f"Ubicación: {unit.location.full_code if unit.location else '—'}",
            ],
        }
    if kind == "location":
        location = db.get(Location, entity_id)
        if location is None:
            location = db.scalars(
                select(Location).where(Location.full_code == entity_id.upper())
            ).first()
        if location is None:
            raise NotFoundError("Ubicación", entity_id)
        payload = build_payload(QRKind.LOCATION, location.full_code)
        return {
            "payload": payload,
            "kind": "location",
            "title": location.full_code,
            "code": location.full_code,
            "lines": [
                f"Almacén: {location.warehouse.code}",
                f"Pasillo {location.aisle} · Estantería {location.rack}",
                f"Nivel {location.level} · Posición {location.position}",
            ],
        }
    if kind == "employee":
        employee = db.get(Employee, entity_id)
        if employee is None:
            raise NotFoundError("Trabajador", entity_id)
        payload = build_payload(QRKind.EMPLOYEE, employee.code)
        return {
            "payload": payload,
            "kind": "employee",
            "title": employee.full_name,
            "code": employee.code,
            "lines": [f"{employee.position} · {employee.department}"],
        }
    raise ValidationError("Tipo de etiqueta no soportado.", details={"kind": kind})
