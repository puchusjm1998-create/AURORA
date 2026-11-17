"""Stock reservations: keep units available for a future outbound operation."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import PermissionCode, ReservationStatus
from app.core.errors import ConflictError, NotFoundError
from app.models import Location, StockReservation, User
from app.schemas import Page, ReservationCreate, ReservationRead
from app.services.audit import record_audit
from app.services.stock import StockEngine

router = APIRouter(prefix="/reservations", tags=["Reservas"])


def _to_read(db: Session, reservation: StockReservation) -> ReservationRead:
    return ReservationRead(
        id=reservation.id,
        reference=reservation.reference,
        product_id=reservation.product_id,
        product_sku=reservation.product.sku,
        product_name=reservation.product.name,
        location_id=reservation.location_id,
        location_code=reservation.location.full_code,
        pallet_id=reservation.pallet_id,
        quantity=reservation.quantity,
        status=reservation.status,
        created_at=reservation.created_at,
        expires_at=reservation.expires_at,
    )


@router.get("", response_model=Page[ReservationRead], summary="Listar reservas")
def list_reservations(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.RESERVATIONS_READ)),
    status: str | None = None,
    product_id: str | None = None,
    reference: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ReservationRead]:
    stmt = select(StockReservation)
    if status:
        stmt = stmt.where(StockReservation.status == status)
    if product_id:
        stmt = stmt.where(StockReservation.product_id == product_id)
    if reference:
        stmt = stmt.where(StockReservation.reference.ilike(f"%{reference}%"))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(stmt.order_by(StockReservation.created_at.desc()).limit(limit).offset(offset)).all()
    )
    return Page(items=[_to_read(db, r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ReservationRead, status_code=201, summary="Crear reserva")
def create_reservation(
    payload: ReservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.RESERVATIONS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ReservationRead:
    engine = StockEngine(db)
    reservation = engine.reserve(
        product_id=payload.product_id,
        location_id=payload.location_id,
        pallet_id=payload.pallet_id,
        quantity=payload.quantity,
        reference=payload.reference,
        actor=user,
        expires_at=payload.expires_at,
    )
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="reservation.created",
        entity_type="stock_reservation",
        entity_id=reservation.id,
        after={
            "product_id": payload.product_id,
            "quantity": payload.quantity,
            "reference": payload.reference,
            "location_id": payload.location_id,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(reservation)
    return _to_read(db, reservation)


@router.post("/{reservation_id}/release", response_model=ReservationRead, summary="Liberar reserva")
def release_reservation(
    reservation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.RESERVATIONS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ReservationRead:
    reservation = db.get(StockReservation, reservation_id)
    if reservation is None:
        raise NotFoundError("Reserva", reservation_id)
    if reservation.status != ReservationStatus.ACTIVE:
        raise ConflictError("La reserva ya no está activa.")
    StockEngine(db).release_reservation(reservation)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="reservation.released",
        entity_type="stock_reservation",
        entity_id=reservation.id,
        after={"reference": reservation.reference, "quantity": reservation.quantity},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(reservation)
    return _to_read(db, reservation)
