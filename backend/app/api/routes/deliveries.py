"""Vehicles and deliveries.

A delivery groups sealed pallets that travel together. The stock effect happens
exactly once: when the delivery is loaded, one audited shipment movement is
created per pallet item at the pallet's location. Before that point pallets can
be added or removed freely; after loading the delivery is immutable apart from
its transport milestones.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import DeliveryStatus, EmployeeStatus, MovementType, PalletStatus, PermissionCode
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import madrid_day_bounds_utc, utcnow
from app.models import Delivery, DeliveryPallet, Employee, Pallet, User, Vehicle
from app.schemas import (
    DeliveryCreate,
    DeliveryFail,
    DeliveryItemRead,
    DeliveryPalletAdd,
    DeliveryPalletRead,
    DeliveryRead,
    DeliveryUpdate,
    Message,
    Page,
    VehicleCreate,
    VehicleRead,
    VehicleUpdate,
)
from app.services.audit import record_audit
from app.services.sequences import next_code
from app.services.stock import StockEngine

router = APIRouter(tags=["Repartos"])

ACTIVE_DELIVERY_STATUSES = (
    DeliveryStatus.DRAFT,
    DeliveryStatus.PREPARING,
    DeliveryStatus.READY,
    DeliveryStatus.LOADED,
    DeliveryStatus.IN_TRANSIT,
)
EDITABLE_STATUSES = (DeliveryStatus.DRAFT, DeliveryStatus.PREPARING)


def _vehicle_to_read(vehicle: Vehicle) -> VehicleRead:
    return VehicleRead(
        id=vehicle.id,
        plate=vehicle.plate,
        model=vehicle.model,
        capacity_kg=vehicle.capacity_kg,
        is_active=vehicle.is_active,
        created_at=vehicle.created_at,
    )


def _to_read(delivery: Delivery) -> DeliveryRead:
    pallets: list[DeliveryPalletRead] = []
    total_units = Decimal("0")
    for link in delivery.pallets:
        pallet = link.pallet
        if pallet is None:
            continue
        items = [
            DeliveryItemRead(
                product_id=item.product_id,
                product_sku=item.product.sku if item.product else "",
                product_name=item.product.name if item.product else "",
                quantity=item.quantity,
                batch_code=item.batch_code,
            )
            for item in pallet.items
        ]
        units = sum((item.quantity for item in pallet.items), Decimal("0"))
        total_units += units
        pallets.append(
            DeliveryPalletRead(
                pallet_id=pallet.id,
                pallet_code=pallet.code,
                status=pallet.status,
                location_code=pallet.location.full_code if pallet.location else None,
                total_units=units,
                items=items,
            )
        )
    driver = delivery.driver
    return DeliveryRead(
        id=delivery.id,
        reference=delivery.reference,
        status=delivery.status,
        destination_name=delivery.destination_name,
        destination_address=delivery.destination_address,
        vehicle_id=delivery.vehicle_id,
        vehicle_plate=delivery.vehicle.plate if delivery.vehicle else None,
        driver_employee_id=delivery.driver_employee_id,
        driver_name=f"{driver.first_name} {driver.last_name}" if driver else None,
        planned_departure=delivery.planned_departure,
        departed_at=delivery.departed_at,
        delivered_at=delivery.delivered_at,
        notes=delivery.notes,
        pallets=pallets,
        total_units=total_units,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
    )


def _get_delivery(db: Session, delivery_id: str) -> Delivery:
    delivery = db.get(Delivery, delivery_id)
    if delivery is None:
        raise NotFoundError("Reparto", delivery_id)
    return delivery


def _check_vehicle(db: Session, vehicle_id: str | None, *, require_active: bool = True) -> None:
    if not vehicle_id:
        return
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError("Vehículo", vehicle_id)
    if require_active and not vehicle.is_active:
        raise ValidationError("El vehículo está desactivado.")


def _check_driver(db: Session, employee_id: str | None) -> None:
    if not employee_id:
        return
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Trabajador", employee_id)
    if employee.status == EmployeeStatus.INACTIVE:
        raise ValidationError("No se puede asignar un reparto a un trabajador inactivo.")


def _audit(db: Session, delivery: Delivery, user: User, meta: RequestMeta, action: str, **after) -> None:
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action=action,
        entity_type="delivery",
        entity_id=delivery.id,
        after={"status": delivery.status.value, "reference": delivery.reference, **after},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
@router.get("/vehicles", response_model=Page[VehicleRead], summary="Listar vehículos")
def list_vehicles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.DELIVERIES_READ)),
    is_active: bool | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[VehicleRead]:
    stmt = select(Vehicle)
    if is_active is not None:
        stmt = stmt.where(Vehicle.is_active.is_(is_active))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(db.scalars(stmt.order_by(Vehicle.plate).limit(limit).offset(offset)).all())
    return Page(items=[_vehicle_to_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.post("/vehicles", response_model=VehicleRead, status_code=201, summary="Crear vehículo")
def create_vehicle(
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> VehicleRead:
    vehicle = Vehicle(
        plate=payload.plate.strip().upper(),
        model=payload.model.strip(),
        capacity_kg=payload.capacity_kg,
        is_active=payload.is_active,
    )
    db.add(vehicle)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("Ya existe un vehículo con esa matrícula.", code="duplicate_plate") from None
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="vehicle.created",
        entity_type="vehicle",
        entity_id=vehicle.id,
        after={"plate": vehicle.plate, "model": vehicle.model},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(vehicle)
    return _vehicle_to_read(vehicle)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleRead, summary="Editar vehículo")
def update_vehicle(
    vehicle_id: str,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> VehicleRead:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError("Vehículo", vehicle_id)
    changes = payload.model_dump(exclude_unset=True)
    if "plate" in changes and changes["plate"]:
        changes["plate"] = changes["plate"].strip().upper()
    for key, value in changes.items():
        setattr(vehicle, key, value.strip() if isinstance(value, str) else value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("Ya existe un vehículo con esa matrícula.", code="duplicate_plate") from None
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="vehicle.updated",
        entity_type="vehicle",
        entity_id=vehicle.id,
        after={"fields": sorted(changes.keys())},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(vehicle)
    return _vehicle_to_read(vehicle)


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------
@router.get("/deliveries", response_model=Page[DeliveryRead], summary="Listar repartos")
def list_deliveries(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.DELIVERIES_READ)),
    status: str | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[DeliveryRead]:
    stmt = select(Delivery)
    if status:
        values = [value.strip() for value in status.split(",") if value.strip()]
        stmt = stmt.where(Delivery.status.in_(values))
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Delivery.reference.ilike(term),
                Delivery.destination_name.ilike(term),
                Delivery.destination_address.ilike(term),
            )
        )
    if date_from:
        start, _ = madrid_day_bounds_utc(date_from)
        stmt = stmt.where(Delivery.planned_departure >= start)
    if date_to:
        _, end = madrid_day_bounds_utc(date_to)
        stmt = stmt.where(Delivery.planned_departure <= end)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(stmt.order_by(Delivery.created_at.desc()).limit(limit).offset(offset)).all()
    )
    return Page(items=[_to_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/deliveries/{delivery_id}", response_model=DeliveryRead, summary="Detalle de reparto")
def get_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.DELIVERIES_READ)),
) -> DeliveryRead:
    return _to_read(_get_delivery(db, delivery_id))


@router.post("/deliveries", response_model=DeliveryRead, status_code=201, summary="Crear reparto")
def create_delivery(
    payload: DeliveryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    _check_vehicle(db, payload.vehicle_id)
    _check_driver(db, payload.driver_employee_id)
    delivery = Delivery(
        reference=next_code(db, "delivery"),
        destination_name=payload.destination_name.strip(),
        destination_address=payload.destination_address.strip(),
        vehicle_id=payload.vehicle_id,
        driver_employee_id=payload.driver_employee_id,
        planned_departure=payload.planned_departure,
        notes=payload.notes.strip(),
        created_by=user.id,
    )
    db.add(delivery)
    db.flush()
    _audit(db, delivery, user, meta, "delivery.created")
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.patch("/deliveries/{delivery_id}", response_model=DeliveryRead, summary="Editar reparto")
def update_delivery(
    delivery_id: str,
    payload: DeliveryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status not in EDITABLE_STATUSES:
        raise ConflictError(
            "Solo se pueden editar repartos en borrador o preparación.", code="delivery_locked"
        )
    changes = payload.model_dump(exclude_unset=True)
    if "vehicle_id" in changes:
        _check_vehicle(db, changes["vehicle_id"])
    if "driver_employee_id" in changes:
        _check_driver(db, changes["driver_employee_id"])
    for key in ("destination_name", "destination_address", "notes"):
        if key in changes and changes[key] is not None:
            changes[key] = changes[key].strip()
    for key, value in changes.items():
        setattr(delivery, key, value)
    db.flush()
    _audit(db, delivery, user, meta, "delivery.updated", fields=sorted(changes.keys()))
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post(
    "/deliveries/{delivery_id}/pallets",
    response_model=DeliveryRead,
    status_code=201,
    summary="Añadir palé al reparto",
)
def add_pallet(
    delivery_id: str,
    payload: DeliveryPalletAdd,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status not in EDITABLE_STATUSES:
        raise ConflictError(
            "Solo se pueden añadir palés en borrador o preparación.", code="delivery_locked"
        )
    pallet = db.get(Pallet, payload.pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", payload.pallet_id)
    if pallet.status != PalletStatus.SEALED:
        raise ConflictError(
            "Solo se pueden repartir palés precintados.", code="pallet_not_sealed"
        )
    if not pallet.items:
        raise ValidationError("El palé no tiene mercancía registrada.")
    if pallet.location_id is None:
        raise ValidationError("El palé no está ubicado en el almacén.")
    busy = db.scalars(
        select(DeliveryPallet)
        .join(Delivery, Delivery.id == DeliveryPallet.delivery_id)
        .where(
            DeliveryPallet.pallet_id == pallet.id,
            Delivery.status.in_(ACTIVE_DELIVERY_STATUSES),
        )
    ).first()
    if busy is not None:
        raise ConflictError(
            "El palé ya está asignado a otro reparto activo.", code="pallet_in_delivery"
        )
    link = DeliveryPallet(delivery_id=delivery.id, pallet_id=pallet.id)
    db.add(link)
    db.flush()
    _audit(db, delivery, user, meta, "delivery.pallet_added", pallet=pallet.code)
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.delete(
    "/deliveries/{delivery_id}/pallets/{pallet_id}",
    response_model=DeliveryRead,
    summary="Quitar palé del reparto",
)
def remove_pallet(
    delivery_id: str,
    pallet_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status not in (DeliveryStatus.DRAFT, DeliveryStatus.PREPARING, DeliveryStatus.READY):
        raise ConflictError("El reparto ya no permite cambios de palés.", code="delivery_locked")
    link = db.scalars(
        select(DeliveryPallet).where(
            DeliveryPallet.delivery_id == delivery.id,
            DeliveryPallet.pallet_id == pallet_id,
        )
    ).first()
    if link is None:
        raise NotFoundError("Palé en el reparto", pallet_id)
    code = link.pallet.code if link.pallet else pallet_id
    db.delete(link)
    db.flush()
    _audit(db, delivery, user, meta, "delivery.pallet_removed", pallet=code)
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post(
    "/deliveries/{delivery_id}/prepare",
    response_model=DeliveryRead,
    summary="Iniciar preparación",
)
def prepare_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status != DeliveryStatus.DRAFT:
        raise ConflictError("Solo se puede preparar un reparto en borrador.", code="invalid_transition")
    delivery.status = DeliveryStatus.PREPARING
    _audit(db, delivery, user, meta, "delivery.prepared")
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post("/deliveries/{delivery_id}/ready", response_model=DeliveryRead, summary="Marcar listo")
def ready_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status != DeliveryStatus.PREPARING:
        raise ConflictError(
            "Solo se puede marcar listo un reparto en preparación.", code="invalid_transition"
        )
    if not delivery.pallets:
        raise ValidationError("Añada al menos un palé antes de marcar el reparto como listo.")
    delivery.status = DeliveryStatus.READY
    _audit(db, delivery, user, meta, "delivery.ready", pallets=len(delivery.pallets))
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post(
    "/deliveries/{delivery_id}/load",
    response_model=DeliveryRead,
    summary="Cargar y expedir mercancía",
)
def load_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status != DeliveryStatus.READY:
        raise ConflictError("Solo se puede cargar un reparto listo.", code="invalid_transition")
    if not delivery.pallets:
        raise ValidationError("El reparto no tiene palés.")
    engine = StockEngine(db)
    movements = 0
    for link in delivery.pallets:
        pallet = link.pallet
        if pallet is None:
            continue
        if pallet.status != PalletStatus.SEALED:
            raise ConflictError(
                f"El palé {pallet.code} ya no está precintado.", code="pallet_not_sealed"
            )
        if not pallet.items:
            raise ValidationError(f"El palé {pallet.code} no tiene mercancía.")
        for item in pallet.items:
            engine.create_movement(
                actor=user,
                movement_type=MovementType.SHIPMENT,
                product_id=item.product_id,
                quantity=item.quantity,
                from_location_id=pallet.location_id,
                from_pallet_id=pallet.id,
                worker_id=delivery.driver_employee_id,
                reason=f"Reparto {delivery.reference} · {delivery.destination_name}",
                document_ref=delivery.reference,
                confirm=True,
                physical_confirmed=True,
                ip=meta.ip,
                user_agent=meta.user_agent,
            )
            movements += 1
        pallet.status = PalletStatus.IN_TRANSIT
        pallet.location_id = None
    delivery.status = DeliveryStatus.LOADED
    _audit(
        db,
        delivery,
        user,
        meta,
        "delivery.loaded",
        movements=movements,
        pallets=len(delivery.pallets),
    )
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post(
    "/deliveries/{delivery_id}/dispatch",
    response_model=DeliveryRead,
    summary="Iniciar el transporte",
)
def dispatch_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status != DeliveryStatus.LOADED:
        raise ConflictError("Solo se puede iniciar el transporte de un reparto cargado.", code="invalid_transition")
    delivery.status = DeliveryStatus.IN_TRANSIT
    delivery.departed_at = utcnow()
    _audit(db, delivery, user, meta, "delivery.dispatched")
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post(
    "/deliveries/{delivery_id}/deliver",
    response_model=DeliveryRead,
    summary="Marcar como entregado",
)
def deliver_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status != DeliveryStatus.IN_TRANSIT:
        raise ConflictError("Solo se puede entregar un reparto en tránsito.", code="invalid_transition")
    delivery.status = DeliveryStatus.DELIVERED
    delivery.delivered_at = utcnow()
    for link in delivery.pallets:
        if link.pallet is not None:
            link.pallet.status = PalletStatus.SHIPPED
    _audit(db, delivery, user, meta, "delivery.delivered")
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post(
    "/deliveries/{delivery_id}/fail",
    response_model=DeliveryRead,
    summary="Registrar entrega fallida",
)
def fail_delivery(
    delivery_id: str,
    payload: DeliveryFail,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status != DeliveryStatus.IN_TRANSIT:
        raise ConflictError("Solo se puede marcar fallido un reparto en tránsito.", code="invalid_transition")
    delivery.status = DeliveryStatus.FAILED
    note = payload.reason.strip()
    delivery.notes = f"{delivery.notes}\nIncidencia: {note}".strip()
    _audit(db, delivery, user, meta, "delivery.failed", reason=note)
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.post(
    "/deliveries/{delivery_id}/cancel",
    response_model=DeliveryRead,
    summary="Cancelar reparto",
)
def cancel_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> DeliveryRead:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status not in (DeliveryStatus.DRAFT, DeliveryStatus.PREPARING, DeliveryStatus.READY):
        raise ConflictError(
            "Solo se puede cancelar antes de cargar la mercancía.", code="invalid_transition"
        )
    for link in list(delivery.pallets):
        db.delete(link)
    delivery.status = DeliveryStatus.CANCELLED
    _audit(db, delivery, user, meta, "delivery.cancelled")
    db.commit()
    db.refresh(delivery)
    return _to_read(delivery)


@router.delete("/deliveries/{delivery_id}", response_model=Message, summary="Eliminar borrador")
def delete_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.DELIVERIES_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    delivery = _get_delivery(db, delivery_id)
    if delivery.status != DeliveryStatus.DRAFT:
        raise ConflictError("Solo se pueden eliminar repartos en borrador.", code="invalid_transition")
    for link in list(delivery.pallets):
        db.delete(link)
    db.delete(delivery)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="delivery.deleted",
        entity_type="delivery",
        entity_id=delivery_id,
        after={"reference": delivery.reference},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    return Message(message="Reparto eliminado.")
