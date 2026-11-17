"""Dashboard KPIs, audit trail access and CSV reporting."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import ValidationError
from app.core.timeutils import madrid_day_bounds_utc, utcnow
from app.services.reservations import expire_due
from app.models import (
    AuditLog,
    Employee,
    Invoice,
    Location,
    Pallet,
    Product,
    StockLevel,
    StockMovement,
    StockReservation,
    Task,
    User,
    Warehouse,
)
from app.schemas import (
    AuditRead,
    DashboardKpis,
    DashboardRead,
    Page,
    WarehouseOccupancy,
)

router = APIRouter(tags=["Panel e informes"])

MOVEMENT_LABELS = {
    "reception": "Recepción",
    "shipment": "Expedición",
    "internal_move": "Movimiento interno",
    "relocation": "Reubicación",
    "picking": "Preparación",
    "replenishment": "Reposición",
    "putaway": "Estocaje",
    "return": "Devolución",
    "adjustment": "Ajuste",
    "load": "Carga",
    "unload": "Descarga",
}


@router.get("/dashboard", response_model=DashboardRead, summary="Panel de control")
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> DashboardRead:
    start, end = madrid_day_bounds_utc(date.today())

    products_total = int(db.scalar(select(func.count(Product.id))) or 0)
    products_active = int(
        db.scalar(select(func.count(Product.id)).where(Product.is_active.is_(True))) or 0
    )
    locations_total = int(db.scalar(select(func.count(Location.id))) or 0)
    capacity_total = int(db.scalar(select(func.coalesce(func.sum(Location.capacity_pallets), 0))) or 0)

    occupied_locations = int(
        db.scalar(
            select(func.count(distinct(StockLevel.location_id))).where(StockLevel.quantity > 0)
        )
        or 0
    )
    pallet_locations = int(
        db.scalar(
            select(func.count(distinct(Pallet.location_id))).where(
                Pallet.status.in_(["open", "sealed"]), Pallet.location_id.isnot(None)
            )
        )
        or 0
    )
    occupied = max(occupied_locations, pallet_locations)
    occupancy_pct = round((occupied / locations_total) * 100, 1) if locations_total else 0.0

    pallets_stored = int(
        db.scalar(select(func.count(Pallet.id)).where(Pallet.status == "sealed")) or 0
    )
    pallets_open = int(db.scalar(select(func.count(Pallet.id)).where(Pallet.status == "open")) or 0)

    total_units = Decimal(
        str(db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0))) or 0)
    )
    stock_value = Decimal(
        str(
            db.scalar(
                select(
                    func.coalesce(
                        func.sum(StockLevel.quantity * Product.purchase_price), 0
                    )
                ).join(Product, Product.id == StockLevel.product_id)
            )
            or 0
        )
    ).quantize(Decimal("0.01"))

    today_counts = dict(
        db.execute(
            select(StockMovement.movement_type, func.count(StockMovement.id))
            .where(
                StockMovement.created_at >= start,
                StockMovement.created_at <= end,
                StockMovement.status == "confirmed",
            )
            .group_by(StockMovement.movement_type)
        ).all()
    )
    movements_today = sum(int(v) for v in today_counts.values())
    receptions_today = int(today_counts.get("reception", 0)) + int(today_counts.get("return", 0))
    shipments_today = int(today_counts.get("shipment", 0)) + int(today_counts.get("picking", 0))

    movements_draft = int(
        db.scalar(select(func.count(StockMovement.id)).where(StockMovement.status == "draft")) or 0
    )

    stock_subq = (
        select(StockLevel.product_id, func.sum(StockLevel.quantity).label("qty"))
        .group_by(StockLevel.product_id)
        .subquery()
    )
    low_stock_count = int(
        db.scalar(
            select(func.count(Product.id))
            .outerjoin(stock_subq, stock_subq.c.product_id == Product.id)
            .where(
                Product.is_active.is_(True),
                Product.min_stock > 0,
                func.coalesce(stock_subq.c.qty, 0) < Product.min_stock,
            )
        )
        or 0
    )

    expire_due(db)
    pending_invoices = int(
        db.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.status.in_(["received", "in_review", "discrepancy"])
            )
        )
        or 0
    )
    workers_active = int(
        db.scalar(select(func.count(Employee.id)).where(Employee.status == "active")) or 0
    )

    open_task_statuses = ["pending", "in_progress", "blocked"]
    open_tasks = int(
        db.scalar(select(func.count(Task.id)).where(Task.status.in_(open_task_statuses))) or 0
    )
    overdue_tasks = int(
        db.scalar(
            select(func.count(Task.id)).where(
                Task.status.in_(open_task_statuses),
                Task.due_at.isnot(None),
                Task.due_at < utcnow(),
            )
        )
        or 0
    )
    active_reservations = int(
        db.scalar(
            select(func.count(StockReservation.id)).where(StockReservation.status == "active")
        )
        or 0
    )
    reserved_units = Decimal(
        str(
            db.scalar(
                select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
                    StockReservation.status == "active"
                )
            )
            or 0
        )
    )

    kpis = DashboardKpis(
        products=products_total,
        active_products=products_active,
        locations=locations_total,
        occupancy_pct=occupancy_pct,
        pallets_stored=pallets_stored,
        pallets_open=pallets_open,
        total_units=total_units,
        stock_value=stock_value,
        movements_today=movements_today,
        receptions_today=receptions_today,
        shipments_today=shipments_today,
        movements_draft=movements_draft,
        low_stock_products=low_stock_count,
        pending_invoices=pending_invoices,
        workers_active=workers_active,
        open_tasks=open_tasks,
        overdue_tasks=overdue_tasks,
        active_reservations=active_reservations,
        reserved_units=reserved_units,
    )

    occupancy_rows = db.execute(
        select(
            Warehouse.code,
            Warehouse.name,
            func.count(distinct(Location.id)),
            func.coalesce(func.sum(Location.capacity_pallets), 0),
        )
        .join(Location, Location.warehouse_id == Warehouse.id, isouter=True)
        .group_by(Warehouse.code, Warehouse.name)
        .order_by(Warehouse.code)
    ).all()
    occupancy: list[WarehouseOccupancy] = []
    for code, name, location_count, capacity in occupancy_rows:
        occupied_count = db.scalar(
            select(func.count(distinct(StockLevel.location_id)))
            .join(Location, Location.id == StockLevel.location_id)
            .join(Warehouse, Warehouse.id == Location.warehouse_id)
            .where(Warehouse.code == code, StockLevel.quantity > 0)
        )
        occupancy.append(
            WarehouseOccupancy(
                warehouse_code=code,
                warehouse_name=name,
                locations=int(location_count or 0),
                occupied=int(occupied_count or 0),
                capacity_pallets=int(capacity or 0),
            )
        )

    top_rows = db.execute(
        select(
            Product.sku,
            Product.name,
            func.sum(StockLevel.quantity),
            func.sum(StockLevel.quantity * Product.purchase_price),
        )
        .join(StockLevel, StockLevel.product_id == Product.id)
        .group_by(Product.id, Product.sku, Product.name)
        .order_by(func.sum(StockLevel.quantity * Product.purchase_price).desc())
        .limit(5)
    ).all()
    top_products = [
        {"sku": sku, "name": name, "quantity": str(qty or 0), "value": str(value or 0)}
        for sku, name, qty, value in top_rows
    ]

    low_rows = db.execute(
        select(
            Product.sku,
            Product.name,
            Product.min_stock,
            func.coalesce(stock_subq.c.qty, 0),
        )
        .outerjoin(stock_subq, stock_subq.c.product_id == Product.id)
        .where(Product.is_active.is_(True), Product.min_stock > 0)
        .where(func.coalesce(stock_subq.c.qty, 0) < Product.min_stock)
        .order_by(func.coalesce(stock_subq.c.qty, 0).asc())
        .limit(5)
    ).all()
    low_stock = [
        {"sku": sku, "name": name, "min_stock": str(minimum), "on_hand": str(qty)}
        for sku, name, minimum, qty in low_rows
    ]

    recent = list(
        db.scalars(
            select(StockMovement).order_by(StockMovement.created_at.desc()).limit(8)
        ).all()
    )
    recent_activity = [
        {
            "id": m.id,
            "reference": m.reference,
            "type": m.movement_type.value,
            "type_label": MOVEMENT_LABELS.get(m.movement_type.value, m.movement_type.value),
            "status": m.status.value,
            "product": m.product.name,
            "quantity": str(m.quantity),
            "uom": m.product.uom,
            "from_location": m.from_location.full_code if m.from_location else None,
            "to_location": m.to_location.full_code if m.to_location else None,
            "created_at": (
                m.created_at.isoformat() + ("" if m.created_at.tzinfo else "Z")
            ),
        }
        for m in recent
    ]

    return DashboardRead(
        kpis=kpis,
        warehouse_occupancy=occupancy,
        top_products=top_products,
        low_stock=low_stock,
        recent_activity=recent_activity,
    )


@router.get("/audit", response_model=Page[AuditRead], summary="Registro de auditoría")
def list_audit(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.AUDIT_READ)),
    action: str | None = None,
    entity_type: str | None = None,
    actor: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[AuditRead]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if actor:
        stmt = stmt.where(AuditLog.actor_label.ilike(f"%{actor}%"))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    )
    items = [AuditRead.model_validate(row) for row in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


def _csv_response(filename: str, header: list[str], rows: list[list[str]]) -> StreamingResponse:
    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM so Excel opens UTF-8 correctly
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    content = buffer.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/inventory.csv", summary="Informe de inventario (CSV)")
def inventory_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
    warehouse_id: str | None = None,
    only_positive: bool = True,
) -> StreamingResponse:
    stmt = (
        select(
            Product.sku,
            Product.name,
            Product.category,
            Product.uom,
            Warehouse.code,
            Location.full_code,
            Pallet.code,
            StockLevel.quantity,
            StockLevel.reserved_quantity,
            Product.purchase_price,
            Product.unit_price,
            StockLevel.updated_at,
        )
        .join(Product, Product.id == StockLevel.product_id)
        .join(Location, Location.id == StockLevel.location_id)
        .join(Warehouse, Warehouse.id == Location.warehouse_id)
        .outerjoin(Pallet, Pallet.id == StockLevel.pallet_id)
    )
    if warehouse_id:
        stmt = stmt.where(Warehouse.id == warehouse_id)
    if only_positive:
        stmt = stmt.where(StockLevel.quantity > 0)
    rows = db.execute(stmt.order_by(Product.sku, Location.full_code)).all()
    data = [
        [
            sku,
            name,
            category,
            uom,
            warehouse,
            location,
            pallet or "",
            f"{Decimal(str(qty)):.3f}",
            f"{Decimal(str(reserved)):.3f}",
            f"{(Decimal(str(qty)) - Decimal(str(reserved))):.3f}",
            f"{Decimal(str(purchase)):.2f}",
            f"{Decimal(str(price)):.2f}",
            f"{(Decimal(str(qty)) * Decimal(str(purchase))):.2f}",
            updated.isoformat() if updated else "",
        ]
        for sku, name, category, uom, warehouse, location, pallet, qty, reserved, purchase, price, updated in rows
    ]
    return _csv_response(
        f"aurora-inventario-{date.today().isoformat()}.csv",
        [
            "SKU", "Producto", "Categoría", "Ud.", "Almacén", "Ubicación", "Palé",
            "Físico", "Reservado", "Disponible", "Precio compra", "Precio venta",
            "Valor", "Actualizado (UTC)",
        ],
        data,
    )


@router.get("/reports/movements.csv", summary="Informe de movimientos (CSV)")
def movements_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> StreamingResponse:
    stmt = (
        select(
            StockMovement.reference,
            StockMovement.created_at,
            StockMovement.movement_type,
            StockMovement.status,
            Product.sku,
            Product.name,
            StockMovement.quantity,
            StockMovement.from_location_id,
            StockMovement.to_location_id,
            StockMovement.batch_code,
            StockMovement.reason,
            StockMovement.document_ref,
            StockMovement.physical_confirmed,
        )
        .join(Product, Product.id == StockMovement.product_id)
    )
    if date_from:
        stmt = stmt.where(StockMovement.created_at >= date_from)
    if date_to:
        stmt = stmt.where(StockMovement.created_at <= date_to)
    rows = db.execute(stmt.order_by(StockMovement.created_at.desc())).all()

    location_codes = {
        loc.id: loc.full_code for loc in db.scalars(select(Location)).all()
    }
    data = [
        [
            reference,
            created.isoformat() if created else "",
            MOVEMENT_LABELS.get(mtype, str(mtype)),
            str(status),
            sku,
            name,
            f"{Decimal(str(qty)):.3f}",
            location_codes.get(from_id, ""),
            location_codes.get(to_id, ""),
            batch or "",
            reason or "",
            document_ref or "",
            "Sí" if confirmed else "No",
        ]
        for reference, created, mtype, status, sku, name, qty, from_id, to_id, batch, reason, document_ref, confirmed in rows
    ]
    return _csv_response(
        f"aurora-movimientos-{date.today().isoformat()}.csv",
        [
            "Referencia", "Fecha (UTC)", "Tipo", "Estado", "SKU", "Producto",
            "Cantidad", "Origen", "Destino", "Lote", "Motivo", "Documento",
            "Confirmación física",
        ],
        data,
    )


@router.get("/reports/summary", summary="Resumen de valoración de existencias")
def valuation_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.REPORTS_READ)),
) -> dict:
    rows = db.execute(
        select(
            Product.category,
            func.count(distinct(Product.id)),
            func.coalesce(func.sum(StockLevel.quantity), 0),
            func.coalesce(func.sum(StockLevel.quantity * Product.purchase_price), 0),
            func.coalesce(func.sum(StockLevel.quantity * Product.unit_price), 0),
        )
        .join(StockLevel, StockLevel.product_id == Product.id, isouter=True)
        .group_by(Product.category)
        .order_by(Product.category)
    ).all()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "currency": "EUR",
        "categories": [
            {
                "category": category,
                "products": int(products),
                "units": str(qty or 0),
                "purchase_value": str(purchase or 0),
                "sale_value": str(sale or 0),
            }
            for category, products, qty, purchase, sale in rows
        ],
    }
