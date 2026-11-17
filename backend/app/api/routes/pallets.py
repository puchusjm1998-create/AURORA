"""Pallets: build, seal, relocate, ship and label."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.api.serializers import pallet_to_read
from app.core.db import get_db
from app.core.enums import MovementType, PalletStatus, PermissionCode
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Invoice,
    Location,
    Pallet,
    PalletItem,
    Product,
    StockMovement,
    User,
    Warehouse,
)
from app.schemas import (
    Message,
    Page,
    PalletAddItem,
    PalletCreate,
    PalletMove,
    PalletRead,
    PalletShip,
    PalletUpdate,
)
from app.services.sequences import next_code
from app.services.stock import StockEngine
from app.services.audit import record_audit

router = APIRouter(tags=["Palés"])


@router.get("/pallets", response_model=Page[PalletRead], summary="Listar palés")
def list_pallets(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.PALLETS_READ)),
    search: str | None = None,
    status: str | None = None,
    warehouse_id: str | None = None,
    location_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[PalletRead]:
    stmt = select(Pallet)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Pallet.code.ilike(term),
                Pallet.id.in_(
                    select(PalletItem.pallet_id).where(
                        PalletItem.product_id.in_(
                            select(Product.id).where(
                                or_(Product.name.ilike(term), Product.sku.ilike(term))
                            )
                        )
                    )
                ),
            )
        )
    if status:
        stmt = stmt.where(Pallet.status == status)
    if warehouse_id:
        stmt = stmt.where(Pallet.warehouse_id == warehouse_id)
    if location_id:
        stmt = stmt.where(Pallet.location_id == location_id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    pallets = list(
        db.scalars(stmt.order_by(Pallet.code.desc()).limit(limit).offset(offset)).all()
    )
    return Page(items=[pallet_to_read(p) for p in pallets], total=total, limit=limit, offset=offset)


@router.post("/pallets", response_model=PalletRead, status_code=201, summary="Crear palé")
def create_pallet(
    payload: PalletCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.PALLETS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> PalletRead:
    warehouse = db.get(Warehouse, payload.warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", payload.warehouse_id)
    if payload.location_id:
        location = db.get(Location, payload.location_id)
        if location is None:
            raise NotFoundError("Ubicación", payload.location_id)
        if location.warehouse_id != warehouse.id:
            raise ValidationError("La ubicación no pertenece al almacén indicado.")
        occupied = db.scalar(
            select(func.count(Pallet.id)).where(
                Pallet.location_id == location.id,
                Pallet.status.in_([PalletStatus.OPEN, PalletStatus.SEALED]),
            )
        )
        if int(occupied or 0) >= location.capacity_pallets:
            raise ConflictError(
                f"La ubicación {location.full_code} está completa (capacidad {location.capacity_pallets})."
            )
    if payload.invoice_id and db.get(Invoice, payload.invoice_id) is None:
        raise NotFoundError("Factura", payload.invoice_id)
    pallet = Pallet(
        code=next_code(db, "pallet"),
        warehouse_id=warehouse.id,
        location_id=payload.location_id,
        notes=payload.notes,
        gross_weight_kg=payload.gross_weight_kg,
        invoice_id=payload.invoice_id,
        created_by=user.id,
        status=PalletStatus.OPEN,
    )
    db.add(pallet)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="pallet.created",
        entity_type="pallet",
        entity_id=pallet.id,
        after={"code": pallet.code, "warehouse": warehouse.code},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(pallet)
    return pallet_to_read(pallet)


@router.get("/pallets/{pallet_id}", response_model=PalletRead, summary="Consultar palé")
def get_pallet(
    pallet_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.PALLETS_READ)),
) -> PalletRead:
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    return pallet_to_read(pallet)


@router.get("/pallets/by-code/{code}", response_model=PalletRead, summary="Palé por código")
def get_pallet_by_code(
    code: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.PALLETS_READ)),
) -> PalletRead:
    pallet = db.scalars(select(Pallet).where(Pallet.code == code.upper())).first()
    if pallet is None:
        raise NotFoundError("Palé", code)
    return pallet_to_read(pallet)


@router.patch("/pallets/{pallet_id}", response_model=PalletRead, summary="Modificar palé")
def update_pallet(
    pallet_id: str,
    payload: PalletUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.PALLETS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> PalletRead:
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    if pallet.status in {PalletStatus.SHIPPED, PalletStatus.IN_TRANSIT}:
        raise ConflictError("No se puede modificar un palé expedido o en tránsito.")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(pallet, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="pallet.updated",
        entity_type="pallet",
        entity_id=pallet.id,
        after=changes,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(pallet)
    return pallet_to_read(pallet)


@router.post("/pallets/{pallet_id}/items", response_model=PalletRead, summary="Añadir mercancía al palé")
def add_pallet_item(
    pallet_id: str,
    payload: PalletAddItem,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.PALLETS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> PalletRead:
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    if pallet.status != PalletStatus.OPEN:
        raise ConflictError("Solo puede añadirse mercancía a un palé abierto.")
    if not pallet.location_id:
        raise ValidationError("Asigne una ubicación al palé antes de añadir mercancía.")
    product = db.get(Product, payload.product_id)
    if product is None:
        raise NotFoundError("Producto", payload.product_id)

    if payload.invoice_line_id:
        from app.models import InvoiceLine

        line = db.get(InvoiceLine, payload.invoice_line_id)
        if line is None:
            raise NotFoundError("Línea de factura", payload.invoice_line_id)
        if line.invoice_id != (payload.invoice_id or pallet.invoice_id):
            raise ValidationError("La línea no pertenece a la factura del palé.")

    engine = StockEngine(db)
    movement = engine.create_movement(
        actor=user,
        movement_type=MovementType.RECEPTION,
        product_id=product.id,
        quantity=payload.quantity,
        to_location_id=pallet.location_id,
        to_pallet_id=pallet.id,
        batch_code=payload.batch_code,
        invoice_id=payload.invoice_id or pallet.invoice_id,
        invoice_line_id=payload.invoice_line_id,
        unit_serials=payload.unit_serials,
        reason=f"Estocaje en palé {pallet.code}",
        confirm=True,
        physical_confirmed=True,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )

    item = db.scalars(
        select(PalletItem).where(
            PalletItem.pallet_id == pallet.id,
            PalletItem.product_id == product.id,
            PalletItem.batch_code == payload.batch_code,
        )
    ).first()
    if item:
        item.quantity += payload.quantity
    else:
        db.add(
            PalletItem(
                pallet_id=pallet.id,
                product_id=product.id,
                quantity=payload.quantity,
                batch_code=payload.batch_code,
            )
        )
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="pallet.item_added",
        entity_type="pallet",
        entity_id=pallet.id,
        after={
            "product": product.sku,
            "quantity": payload.quantity,
            "movement": movement.reference,
            "batch_code": payload.batch_code,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(pallet)
    return pallet_to_read(pallet)


@router.delete("/pallets/{pallet_id}/items/{item_id}", response_model=PalletRead, summary="Retirar mercancía")
def remove_pallet_item(
    pallet_id: str,
    item_id: str,
    destination_location_id: str = Query(..., description="Ubicación de destino de la mercancía retirada"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.PALLETS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> PalletRead:
    """Move the goods from the pallet to a warehouse location and drop the line.

    The stock never disappears: a transfer movement is written before the line
    is removed, so the ledger stays complete.
    """
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    if pallet.status != PalletStatus.OPEN:
        raise ConflictError("Solo puede retirarse mercancía de un palé abierto.")
    item = db.get(PalletItem, item_id)
    if item is None or item.pallet_id != pallet.id:
        raise NotFoundError("Línea de palé", item_id)
    engine = StockEngine(db)
    movement = engine.create_movement(
        actor=user,
        movement_type=MovementType.INTERNAL_MOVE,
        product_id=item.product_id,
        quantity=item.quantity,
        from_location_id=pallet.location_id,
        from_pallet_id=pallet.id,
        to_location_id=destination_location_id,
        batch_code=item.batch_code,
        reason=f"Retirada de mercancía del palé {pallet.code}",
        confirm=True,
        physical_confirmed=True,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    removed = {"product_id": item.product_id, "quantity": str(item.quantity)}
    db.delete(item)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="pallet.item_removed",
        entity_type="pallet",
        entity_id=pallet.id,
        after={**removed, "movement": movement.reference, "destination": destination_location_id},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(pallet)
    return pallet_to_read(pallet)


@router.post("/pallets/{pallet_id}/seal", response_model=PalletRead, summary="Precintar palé")
def seal_pallet(
    pallet_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.PALLETS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> PalletRead:
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    StockEngine(db).seal_pallet(pallet, actor=user)
    db.commit()
    db.refresh(pallet)
    return pallet_to_read(pallet)


@router.post("/pallets/{pallet_id}/move", response_model=Message, summary="Reubicar palé")
def move_pallet(
    pallet_id: str,
    payload: PalletMove,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.PALLETS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    if PermissionCode.MOVEMENTS_CONFIRM.value not in _permissions(db, user):
        raise ConflictError("No dispone de permiso para confirmar el movimiento del palé.")
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    movements = StockEngine(db).move_pallet(
        pallet,
        actor=user,
        destination_location_id=payload.destination_location_id,
        worker_id=payload.worker_id,
        reason=payload.reason,
        ip=meta.ip,
    )
    db.commit()
    return Message(
        message=f"Palé {pallet.code} reubicado correctamente.",
        details={"movements": [m.reference for m in movements]},
    )


@router.post("/pallets/{pallet_id}/ship", response_model=Message, summary="Expedir palé")
def ship_pallet(
    pallet_id: str,
    payload: PalletShip,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.PALLETS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    if PermissionCode.MOVEMENTS_CONFIRM.value not in _permissions(db, user):
        raise ConflictError("No dispone de permiso para confirmar la expedición.")
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    movements = StockEngine(db).ship_pallet(
        pallet,
        actor=user,
        worker_id=payload.worker_id,
        document_ref=payload.document_ref,
        reason=payload.reason,
        ip=meta.ip,
    )
    db.commit()
    return Message(
        message=f"Palé {pallet.code} expedido correctamente.",
        details={"movements": [m.reference for m in movements]},
    )


@router.get("/pallets/{pallet_id}/movements", response_model=Page[dict], summary="Movimientos del palé")
def pallet_movements(
    pallet_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.PALLETS_READ)),
    limit: int = Query(50, ge=1, le=200),
) -> Page[dict]:
    pallet = db.get(Pallet, pallet_id)
    if pallet is None:
        raise NotFoundError("Palé", pallet_id)
    stmt = (
        select(StockMovement)
        .where(
            or_(
                StockMovement.from_pallet_id == pallet_id,
                StockMovement.to_pallet_id == pallet_id,
                StockMovement.pallet_id == pallet_id,
            )
        )
        .order_by(StockMovement.created_at.desc())
        .limit(limit)
    )
    movements = list(db.scalars(stmt).all())
    items = [
        {
            "id": m.id,
            "reference": m.reference,
            "type": m.movement_type.value,
            "status": m.status.value,
            "product": m.product.name,
            "quantity": str(m.quantity),
            "created_at": (m.created_at.isoformat() + ("" if m.created_at.tzinfo else "Z")),
            "reason": m.reason,
        }
        for m in movements
    ]
    return Page(items=items, total=len(items), limit=limit, offset=0)


def _permissions(db: Session, user: User) -> set[str]:
    from app.core.permissions import permissions_for_role

    return set(permissions_for_role(db, user.role_id))
