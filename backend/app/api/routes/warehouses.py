"""Warehouses and storage locations."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.api.serializers import location_to_read
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import Location, Pallet, StockLevel, User, Warehouse
from app.schemas import (
    LocationCreate,
    LocationRead,
    LocationUpdate,
    Message,
    Page,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["Almacenes y ubicaciones"])


def _warehouse_to_read(db: Session, warehouse: Warehouse) -> WarehouseRead:
    count = db.scalar(select(func.count(Location.id)).where(Location.warehouse_id == warehouse.id)) or 0
    data = WarehouseRead.model_validate(warehouse)
    data.location_count = int(count)
    return data


@router.get("/warehouses", response_model=Page[WarehouseRead], summary="Listar almacenes")
def list_warehouses(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.LOCATIONS_READ)),
    include_inactive: bool = Query(False),
) -> Page[WarehouseRead]:
    stmt = select(Warehouse).order_by(Warehouse.code)
    if not include_inactive:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    warehouses = list(db.scalars(stmt).all())
    items = [_warehouse_to_read(db, w) for w in warehouses]
    return Page(items=items, total=len(items), limit=len(items), offset=0)


@router.post("/warehouses", response_model=WarehouseRead, status_code=201, summary="Crear almacén")
def create_warehouse(
    payload: WarehouseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> WarehouseRead:
    code = payload.code.upper().strip()
    if db.scalars(select(Warehouse).where(Warehouse.code == code)).first():
        raise ConflictError(f"Ya existe un almacén con el código {code}.")
    warehouse = Warehouse(
        code=code,
        name=payload.name,
        address=payload.address,
        city=payload.city,
        postal_code=payload.postal_code,
        country=payload.country.upper(),
        timezone=payload.timezone,
    )
    db.add(warehouse)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="warehouse.created",
        entity_type="warehouse",
        entity_id=warehouse.id,
        after={"code": warehouse.code, "name": warehouse.name},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(warehouse)
    return _warehouse_to_read(db, warehouse)


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseRead, summary="Consultar almacén")
def get_warehouse(
    warehouse_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.LOCATIONS_READ)),
) -> WarehouseRead:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", warehouse_id)
    return _warehouse_to_read(db, warehouse)


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseRead, summary="Modificar almacén")
def update_warehouse(
    warehouse_id: str,
    payload: WarehouseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> WarehouseRead:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", warehouse_id)
    before = {"name": warehouse.name, "is_active": warehouse.is_active}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(warehouse, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="warehouse.updated",
        entity_type="warehouse",
        entity_id=warehouse.id,
        before=before,
        after=payload.model_dump(exclude_unset=True),
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(warehouse)
    return _warehouse_to_read(db, warehouse)


@router.get("/locations", response_model=Page[LocationRead], summary="Listar ubicaciones")
def list_locations(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.LOCATIONS_READ)),
    warehouse_id: str | None = None,
    aisle: str | None = None,
    search: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[LocationRead]:
    stmt = select(Location)
    count_stmt = select(func.count(Location.id))
    filters = []
    if warehouse_id:
        filters.append(Location.warehouse_id == warehouse_id)
    if aisle:
        filters.append(Location.aisle == aisle.upper())
    if is_active is not None:
        filters.append(Location.is_active.is_(is_active))
    if search:
        term = f"%{search.upper()}%"
        filters.append(Location.full_code.ilike(term) | Location.label.ilike(f"%{search}%"))
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)
    total = int(db.scalar(count_stmt) or 0)
    locations = list(
        db.scalars(stmt.order_by(Location.full_code).limit(limit).offset(offset)).all()
    )
    ids = [loc.id for loc in locations]
    pallet_counts: dict[str, int] = {}
    unit_counts: dict[str, Decimal] = {}
    if ids:
        pallet_rows = db.execute(
            select(Pallet.location_id, func.count(Pallet.id))
            .where(Pallet.location_id.in_(ids), Pallet.status.in_(["open", "sealed"]))
            .group_by(Pallet.location_id)
        ).all()
        pallet_counts = {row[0]: int(row[1]) for row in pallet_rows}
        unit_rows = db.execute(
            select(StockLevel.location_id, func.coalesce(func.sum(StockLevel.quantity), 0))
            .where(StockLevel.location_id.in_(ids))
            .group_by(StockLevel.location_id)
        ).all()
        unit_counts = {row[0]: Decimal(str(row[1])) for row in unit_rows}
    items = [
        location_to_read(
            db,
            loc,
            pallet_counts.get(loc.id, 0),
            unit_counts.get(loc.id, Decimal("0")),
        )
        for loc in locations
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/locations", response_model=LocationRead, status_code=201, summary="Crear ubicación")
def create_location(
    payload: LocationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> LocationRead:
    warehouse = db.get(Warehouse, payload.warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", payload.warehouse_id)
    aisle, rack = payload.aisle.upper(), payload.rack.upper()
    level, position = payload.level.upper(), payload.position.upper()
    full_code = f"{warehouse.code}-{aisle}-{rack}-{level}-{position}"
    if db.scalars(select(Location).where(Location.full_code == full_code)).first():
        raise ConflictError(f"La ubicación {full_code} ya existe.")
    location = Location(
        warehouse_id=warehouse.id,
        aisle=aisle,
        rack=rack,
        level=level,
        position=position,
        full_code=full_code,
        label=payload.label,
        capacity_pallets=payload.capacity_pallets,
        capacity_units=payload.capacity_units,
        is_pick_face=payload.is_pick_face,
    )
    db.add(location)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="location.created",
        entity_type="location",
        entity_id=location.id,
        after={"code": location.full_code, "capacity_pallets": location.capacity_pallets},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(location)
    return location_to_read(db, location)


@router.get("/locations/by-code/{full_code}", response_model=LocationRead, summary="Ubicación por código")
def get_location_by_code(
    full_code: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.LOCATIONS_READ)),
) -> LocationRead:
    location = db.scalars(select(Location).where(Location.full_code == full_code.upper())).first()
    if location is None:
        raise NotFoundError("Ubicación", full_code)
    return location_to_read(db, location)


@router.get("/locations/{location_id}", response_model=LocationRead, summary="Consultar ubicación")
def get_location(
    location_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.LOCATIONS_READ)),
) -> LocationRead:
    location = db.get(Location, location_id)
    if location is None:
        raise NotFoundError("Ubicación", location_id)
    return location_to_read(db, location)


@router.patch("/locations/{location_id}", response_model=LocationRead, summary="Modificar ubicación")
def update_location(
    location_id: str,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> LocationRead:
    location = db.get(Location, location_id)
    if location is None:
        raise NotFoundError("Ubicación", location_id)
    if payload.is_active is False:
        occupied = db.scalar(
            select(func.count(StockLevel.id)).where(
                StockLevel.location_id == location.id, StockLevel.quantity > 0
            )
        )
        if occupied:
            raise ValidationError("No se puede desactivar una ubicación con existencias.")
    before = {
        "label": location.label,
        "capacity_pallets": location.capacity_pallets,
        "is_active": location.is_active,
        "is_pick_face": location.is_pick_face,
    }
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="location.updated",
        entity_type="location",
        entity_id=location.id,
        before=before,
        after=payload.model_dump(exclude_unset=True),
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(location)
    return location_to_read(db, location)


@router.get("/warehouses/{warehouse_id}/layout", summary="Mapa de ocupación del almacén")
def warehouse_layout(
    warehouse_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.LOCATIONS_READ)),
) -> dict:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", warehouse_id)
    locations = list(
        db.scalars(
            select(Location)
            .where(Location.warehouse_id == warehouse_id)
            .order_by(Location.aisle, Location.rack, Location.level, Location.position)
        ).all()
    )
    pallet_rows = db.execute(
        select(Pallet.location_id, func.count(Pallet.id))
        .where(Pallet.warehouse_id == warehouse_id, Pallet.status.in_(["open", "sealed"]))
        .group_by(Pallet.location_id)
    ).all()
    pallet_counts = {row[0]: int(row[1]) for row in pallet_rows}
    unit_rows = db.execute(
        select(StockLevel.location_id, func.coalesce(func.sum(StockLevel.quantity), 0))
        .where(StockLevel.location_id.in_([loc.id for loc in locations] or [""]))
        .group_by(StockLevel.location_id)
    ).all()
    unit_counts = {row[0]: Decimal(str(row[1])) for row in unit_rows}

    aisles: dict[str, dict] = {}
    for loc in locations:
        aisle = aisles.setdefault(loc.aisle, {"aisle": loc.aisle, "racks": {}})
        rack = aisle["racks"].setdefault(loc.rack, {"rack": loc.rack, "locations": []})
        rack["locations"].append(
            location_to_read(db, loc, pallet_counts.get(loc.id, 0), unit_counts.get(loc.id, Decimal("0")))
        )
    return {
        "warehouse": {
            "id": warehouse.id,
            "code": warehouse.code,
            "name": warehouse.name,
        },
        "aisles": [
            {"aisle": a["aisle"], "racks": list(a["racks"].values())} for a in aisles.values()
        ],
    }


@router.get("/locations/{location_id}/qr", response_model=Message, summary="Datos de etiqueta QR")
def location_qr(
    location_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.LOCATIONS_READ)),
) -> Message:
    location = db.get(Location, location_id)
    if location is None:
        raise NotFoundError("Ubicación", location_id)
    return Message(
        message="Etiqueta QR de ubicación",
        details={"payload": f"aurora://location/{location.full_code}", "code": location.full_code},
    )
