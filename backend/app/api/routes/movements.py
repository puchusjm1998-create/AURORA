"""Stock movements: reception, shipment, transfers and authorised adjustments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import (
    RequestMeta,
    get_request_meta,
    require_permission,
)
from app.api.serializers import movement_to_read
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import AppError, NotFoundError, PermissionDeniedError
from app.models import Location, Pallet, Product, StockMovement, User
from app.schemas import (
    Message,
    MovementCancel,
    MovementConfirm,
    MovementCreate,
    MovementRead,
    Page,
)
from app.services.stock import StockEngine

router = APIRouter(tags=["Movimientos"])


def _movement_reads(db: Session, movements: list[StockMovement]) -> list[MovementRead]:
    user_ids = {m.created_by for m in movements if m.created_by}
    names_map: dict[str, str] = {}
    if user_ids:
        rows = db.execute(
            select(User.id, User.full_name).where(User.id.in_(user_ids))
        ).all()
        names_map = {row[0]: row[1] for row in rows}
        # Relationship-based loading happens per movement; reuse the cached map.
    return [movement_to_read(db, m, names_map) for m in movements]


@router.get("/movements", response_model=Page[MovementRead], summary="Historial de movimientos")
def list_movements(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.MOVEMENTS_READ)),
    movement_type: str | None = None,
    status: str | None = None,
    product_id: str | None = None,
    location_id: str | None = None,
    pallet_id: str | None = None,
    worker_id: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[MovementRead]:
    stmt = select(StockMovement)
    if movement_type:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if status:
        stmt = stmt.where(StockMovement.status == status)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if location_id:
        stmt = stmt.where(
            or_(
                StockMovement.from_location_id == location_id,
                StockMovement.to_location_id == location_id,
            )
        )
    if pallet_id:
        stmt = stmt.where(
            or_(
                StockMovement.from_pallet_id == pallet_id,
                StockMovement.to_pallet_id == pallet_id,
                StockMovement.pallet_id == pallet_id,
            )
        )
    if worker_id:
        stmt = stmt.where(StockMovement.worker_id == worker_id)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                StockMovement.reference.ilike(term),
                StockMovement.document_ref.ilike(term),
                StockMovement.reason.ilike(term),
                StockMovement.product_id.in_(
                    select(Product.id).where(
                        or_(Product.name.ilike(term), Product.sku.ilike(term))
                    )
                ),
            )
        )
    if date_from:
        stmt = stmt.where(StockMovement.created_at >= date_from)
    if date_to:
        stmt = stmt.where(StockMovement.created_at <= date_to)

    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    movements = list(
        db.scalars(
            stmt.order_by(StockMovement.created_at.desc()).limit(limit).offset(offset)
        ).all()
    )
    return Page(items=_movement_reads(db, movements), total=total, limit=limit, offset=offset)


@router.post("/movements", response_model=MovementRead, status_code=201, summary="Registrar movimiento")
def create_movement(
    payload: MovementCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.MOVEMENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> MovementRead:
    key = payload.idempotency_key or idempotency_key
    if payload.confirm and PermissionCode.MOVEMENTS_CONFIRM.value not in _permissions(db, user):
        raise PermissionDeniedError("No puede confirmar movimientos.")
    if payload.movement_type.value == "adjustment" and user.role_level > 2:
        raise PermissionDeniedError(
            "Los ajustes de inventario requieren nivel 1 o 2.",
            code="insufficient_authority",
        )
    engine = StockEngine(db)
    movement = engine.create_movement(
        actor=user,
        movement_type=payload.movement_type,
        product_id=payload.product_id,
        quantity=payload.quantity,
        from_location_id=payload.from_location_id,
        to_location_id=payload.to_location_id,
        from_pallet_id=payload.from_pallet_id,
        to_pallet_id=payload.to_pallet_id,
        worker_id=payload.worker_id,
        batch_code=payload.batch_code,
        reason=payload.reason,
        document_ref=payload.document_ref,
        invoice_id=payload.invoice_id,
        invoice_line_id=payload.invoice_line_id,
        idempotency_key=key,
        unit_serials=payload.unit_serials,
        unit_codes=payload.unit_codes,
        reservation_id=payload.reservation_id,
        confirm=payload.confirm,
        physical_confirmed=payload.physical_confirmed,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(movement)
    return movement_to_read(db, movement)


@router.get("/movements/{movement_id}", response_model=MovementRead, summary="Consultar movimiento")
def get_movement(
    movement_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.MOVEMENTS_READ)),
) -> MovementRead:
    movement = db.get(StockMovement, movement_id)
    if movement is None:
        raise NotFoundError("Movimiento", movement_id)
    return movement_to_read(db, movement)


@router.post("/movements/{movement_id}/confirm", response_model=MovementRead, summary="Confirmar movimiento")
def confirm_movement(
    movement_id: str,
    payload: MovementConfirm,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.MOVEMENTS_CONFIRM)),
    meta: RequestMeta = Depends(get_request_meta),
) -> MovementRead:
    movement = db.get(StockMovement, movement_id)
    if movement is None:
        raise NotFoundError("Movimiento", movement_id)
    engine = StockEngine(db)
    engine.confirm(
        movement,
        actor=user,
        physical_confirmed=payload.physical_confirmed,
        reservation_id=payload.reservation_id,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(movement)
    return movement_to_read(db, movement)


@router.post("/movements/{movement_id}/cancel", response_model=MovementRead, summary="Cancelar movimiento")
def cancel_movement(
    movement_id: str,
    payload: MovementCancel,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.MOVEMENTS_CANCEL)),
    meta: RequestMeta = Depends(get_request_meta),
) -> MovementRead:
    movement = db.get(StockMovement, movement_id)
    if movement is None:
        raise NotFoundError("Movimiento", movement_id)
    StockEngine(db).cancel(movement, actor=user, reason=payload.reason, ip=meta.ip)
    db.commit()
    db.refresh(movement)
    return movement_to_read(db, movement)


@router.get("/movements/meta/types", response_model=Message, summary="Tipos de movimiento")
def movement_types(_: User = Depends(require_permission(PermissionCode.MOVEMENTS_READ))) -> Message:
    return Message(
        message="Tipos de movimiento disponibles",
        details={
            "types": [
                {"value": "reception", "label": "Recepción", "direction": "inbound"},
                {"value": "shipment", "label": "Expedición", "direction": "outbound"},
                {"value": "internal_move", "label": "Movimiento interno", "direction": "transfer"},
                {"value": "relocation", "label": "Reubicación", "direction": "transfer"},
                {"value": "picking", "label": "Preparación de pedidos", "direction": "outbound"},
                {"value": "replenishment", "label": "Reposición", "direction": "transfer"},
                {"value": "putaway", "label": "Estocaje", "direction": "transfer"},
                {"value": "return", "label": "Devolución", "direction": "inbound"},
                {"value": "adjustment", "label": "Ajuste autorizado", "direction": "adjustment"},
                {"value": "load", "label": "Carga", "direction": "outbound"},
                {"value": "unload", "label": "Descarga", "direction": "inbound"},
            ]
        },
    )


def _permissions(db: Session, user: User) -> set[str]:
    from app.core.permissions import permissions_for_role

    return set(permissions_for_role(db, user.role_id))
