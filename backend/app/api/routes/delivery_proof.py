"""Fase 8: seguimiento GPS y firma de entrega de los repartos.

El conductor (nivel 4) usa ``deliveries.track`` para enviar su posición y
firmar la entrega de los repartos que tiene asignados. Lectura y gestión
mantienen ``deliveries.read``/``deliveries.write``. Los puntos GPS y la firma
son evidencias inmutables: no se editan ni se borran por API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    RequestMeta,
    get_request_meta,
    require_any_permission,
    require_permission,
)
from app.api.routes.deliveries import _get_delivery, _to_read
from app.core.db import get_db
from app.core.enums import DeliveryStatus, PalletStatus, PermissionCode
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.timeutils import utcnow
from app.models import Delivery, DeliverySignature, DeliveryTracking, User
from app.schemas import (
    DeliveryRead,
    DeliverySignatureRead,
    DeliveryTrackingCreate,
    DeliveryTrackingRead,
    DeliveryTrackingSummary,
    Page,
)
from app.services.audit import record_audit
from app.services.delivery_proof import (
    point_to_read,
    signature_to_read,
    tracking_summary,
)
from app.services.storage import resolve_stored_path, store_delivery_signature

router = APIRouter(tags=["Prueba de entrega"])

DRIVER_STATUSES = (
    DeliveryStatus.LOADED,
    DeliveryStatus.IN_TRANSIT,
    DeliveryStatus.DELIVERED,
)


def _ensure_access(user: User, delivery: Delivery) -> None:
    """Niveles 1-3 y auditoría ven todos; el nivel 4 solo lo que conduce."""
    if user.role_level != 4:
        return
    employee = user.employee
    if employee is None or delivery.driver_employee_id != employee.id:
        raise PermissionDeniedError("Solo puede operar sobre sus repartos asignados.")


def _ensure_in_transit(delivery: Delivery) -> None:
    if delivery.status != DeliveryStatus.IN_TRANSIT:
        raise ConflictError(
            "El reparto debe estar en tránsito para registrar GPS o firma.",
            code="delivery_not_in_transit",
            details={"status": delivery.status.value},
        )


def _require_complete_location(latitude: float | None, longitude: float | None) -> None:
    if (latitude is None) != (longitude is None):
        raise ValidationError(
            "Envíe latitud y longitud juntas o ninguna de las dos.",
            code="invalid_location",
        )
    if latitude is not None and not (-90 <= latitude <= 90):
        raise ValidationError("Latitud fuera de rango.", code="invalid_location")
    if longitude is not None and not (-180 <= longitude <= 180):
        raise ValidationError("Longitud fuera de rango.", code="invalid_location")


def _points(db: Session, delivery_id: str, limit: int = 200) -> list[DeliveryTracking]:
    rows = list(
        db.scalars(
            select(DeliveryTracking)
            .where(DeliveryTracking.delivery_id == delivery_id)
            .order_by(DeliveryTracking.recorded_at.desc())
            .limit(limit)
        ).all()
    )
    rows.reverse()
    return rows


@router.get(
    "/deliveries/mine",
    response_model=Page[DeliveryRead],
    summary="Mis repartos asignados (conductor)",
)
def my_deliveries(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_TRACK)),
    limit: int = Query(50, ge=1, le=100),
) -> Page[DeliveryRead]:
    if user.employee is None:
        raise PermissionDeniedError("Su usuario no tiene ficha de trabajador asociada.")
    stmt = select(Delivery).where(
        Delivery.driver_employee_id == user.employee.id,
        Delivery.status.in_(DRIVER_STATUSES),
    )
    rows = list(
        db.scalars(stmt.order_by(Delivery.planned_departure.desc()).limit(limit)).all()
    )
    return Page(
        items=[_to_read(row) for row in rows], total=len(rows), limit=limit, offset=0
    )


@router.post(
    "/deliveries/{delivery_id}/tracking",
    response_model=DeliveryTrackingRead,
    status_code=201,
    summary="Registrar posición GPS del reparto",
)
def add_tracking(
    delivery_id: str,
    payload: DeliveryTrackingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_TRACK)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryTrackingRead:
    delivery = _get_delivery(db, delivery_id)
    _ensure_access(user, delivery)
    _ensure_in_transit(delivery)
    point = DeliveryTracking(
        delivery_id=delivery.id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        accuracy_m=payload.accuracy_m,
        speed_mps=payload.speed_mps,
        heading_deg=payload.heading_deg,
        source="browser",
        recorded_at=utcnow(),
        created_by=user.id,
    )
    db.add(point)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="delivery.tracking",
        entity_type="delivery",
        entity_id=delivery.id,
        after={
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "accuracy_m": payload.accuracy_m,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(point)
    return point_to_read(point)


@router.get(
    "/deliveries/{delivery_id}/tracking",
    response_model=DeliveryTrackingSummary,
    summary="Historial GPS del reparto",
)
def get_tracking(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_any_permission(PermissionCode.DELIVERIES_READ, PermissionCode.DELIVERIES_TRACK)
    ),
    limit: int = Query(200, ge=1, le=500),
) -> DeliveryTrackingSummary:
    delivery = _get_delivery(db, delivery_id)
    _ensure_access(user, delivery)
    return tracking_summary(
        delivery_id=delivery.id,
        reference=delivery.reference,
        points=_points(db, delivery.id, limit),
        delivered=delivery.status == DeliveryStatus.DELIVERED,
    )


@router.get(
    "/deliveries/{delivery_id}/tracking/latest",
    response_model=DeliveryTrackingRead,
    summary="Última posición GPS del reparto",
)
def latest_tracking(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_any_permission(PermissionCode.DELIVERIES_READ, PermissionCode.DELIVERIES_TRACK)
    ),
) -> DeliveryTrackingRead:
    delivery = _get_delivery(db, delivery_id)
    _ensure_access(user, delivery)
    point = db.scalars(
        select(DeliveryTracking)
        .where(DeliveryTracking.delivery_id == delivery.id)
        .order_by(DeliveryTracking.recorded_at.desc())
        .limit(1)
    ).first()
    if point is None:
        raise NotFoundError("Posición GPS", delivery.reference)
    return point_to_read(point)


@router.post(
    "/deliveries/{delivery_id}/signature",
    response_model=DeliverySignatureRead,
    status_code=201,
    summary="Firmar la entrega y adjuntar evidencia",
)
async def sign_delivery(
    delivery_id: str,
    signer_name: str = Form(..., min_length=2, max_length=120),
    signer_document: str = Form("", max_length=32),
    mark_delivered: bool = Form(True),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_TRACK)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliverySignatureRead:
    delivery = _get_delivery(db, delivery_id)
    _ensure_access(user, delivery)
    _ensure_in_transit(delivery)
    _require_complete_location(latitude, longitude)
    existing = db.scalars(
        select(DeliverySignature).where(DeliverySignature.delivery_id == delivery.id)
    ).first()
    if existing is not None:
        raise ConflictError(
            "El reparto ya tiene una firma de entrega.", code="delivery_already_signed"
        )

    stored = await store_delivery_signature(file, delivery_reference=delivery.reference)
    signature = DeliverySignature(
        delivery_id=delivery.id,
        signer_name=signer_name.strip(),
        signer_document=signer_document.strip(),
        signature_path=stored.relative_path,
        signature_sha256=stored.sha256,
        mime_type=stored.mime_type,
        size_bytes=stored.size,
        signed_at=utcnow(),
        ip=meta.ip,
        user_agent=(meta.user_agent or "")[:255] or None,
        created_by=user.id,
    )
    db.add(signature)
    if latitude is not None and longitude is not None:
        db.add(
            DeliveryTracking(
                delivery_id=delivery.id,
                latitude=latitude,
                longitude=longitude,
                accuracy_m=None,
                source="signature",
                recorded_at=utcnow(),
                created_by=user.id,
            )
        )
    if mark_delivered:
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = utcnow()
        for link in delivery.pallets:
            if link.pallet is not None:
                link.pallet.status = PalletStatus.SHIPPED
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="delivery.signed",
        entity_type="delivery",
        entity_id=delivery.id,
        after={
            "signer_name": signature.signer_name,
            "sha256": signature.signature_sha256,
            "size_bytes": signature.size_bytes,
            "mark_delivered": mark_delivered,
            "latitude": latitude,
            "longitude": longitude,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    if mark_delivered:
        record_audit(
            db,
            actor_user_id=user.id,
            actor_label=user.full_name,
            action="delivery.delivered",
            entity_type="delivery",
            entity_id=delivery.id,
            after={"via": "signature", "reference": delivery.reference},
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
    db.commit()
    db.refresh(signature)
    return DeliverySignatureRead(**signature_to_read(signature))


@router.get(
    "/deliveries/{delivery_id}/signature",
    response_model=DeliverySignatureRead,
    summary="Consultar la firma de entrega",
)
def get_signature(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_any_permission(PermissionCode.DELIVERIES_READ, PermissionCode.DELIVERIES_TRACK)
    ),
) -> DeliverySignatureRead:
    delivery = _get_delivery(db, delivery_id)
    _ensure_access(user, delivery)
    signature = db.scalars(
        select(DeliverySignature).where(DeliverySignature.delivery_id == delivery.id)
    ).first()
    if signature is None:
        raise NotFoundError("Firma de entrega", delivery.reference)
    return DeliverySignatureRead(**signature_to_read(signature))


@router.get(
    "/deliveries/{delivery_id}/signature/image",
    summary="Descargar la imagen de la firma",
)
def get_signature_image(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_any_permission(PermissionCode.DELIVERIES_READ, PermissionCode.DELIVERIES_TRACK)
    ),
) -> FileResponse:
    delivery = _get_delivery(db, delivery_id)
    _ensure_access(user, delivery)
    signature = db.scalars(
        select(DeliverySignature).where(DeliverySignature.delivery_id == delivery.id)
    ).first()
    if signature is None:
        raise NotFoundError("Firma de entrega", delivery.reference)
    path = resolve_stored_path(signature.signature_path)
    return FileResponse(
        path,
        media_type=signature.mime_type,
        filename=f"firma-{delivery.reference}.png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-SHA256": signature.signature_sha256,
        },
    )
