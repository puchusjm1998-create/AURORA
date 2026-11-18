"""Datos de los informes reutilizables por la API, el correo y los scripts.

Una única consulta alimenta las exportaciones CSV, PDF y Excel, tanto las
descargas manuales como los envíos programados.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Location, Pallet, Product, StockLevel, StockMovement, Warehouse
from app.services.reports import ReportTable, table_as_csv_rows

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

INVENTORY_HEADERS = [
    "SKU", "Producto", "Categoría", "Ud.", "Almacén", "Ubicación", "Palé",
    "Físico", "Reservado", "Disponible", "Precio compra", "Precio venta",
    "Valor", "Actualizado (UTC)",
]
INVENTORY_FORMATS = {7: "qty", 8: "qty", 9: "qty", 10: "money", 11: "money", 12: "money"}
MOVEMENT_HEADERS = [
    "Referencia", "Fecha (UTC)", "Tipo", "Estado", "SKU", "Producto",
    "Cantidad", "Origen", "Destino", "Lote", "Motivo", "Documento",
    "Confirmación física",
]
MOVEMENT_FORMATS = {6: "qty"}


def inventory_table(db: Session, warehouse_id: str | None, only_positive: bool) -> ReportTable:
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

    data: list[list] = []
    total_qty = total_reserved = total_available = total_value = Decimal("0")
    warehouse_label = "Todos"
    for sku, name, category, uom, warehouse, location, pallet, qty, reserved, purchase, price, updated in rows:
        quantity = Decimal(str(qty))
        reserved_qty = Decimal(str(reserved))
        available = quantity - reserved_qty
        value = quantity * Decimal(str(purchase))
        total_qty += quantity
        total_reserved += reserved_qty
        total_available += available
        total_value += value
        data.append(
            [
                sku, name, category, uom, warehouse, location, pallet or "",
                quantity, reserved_qty, available,
                Decimal(str(purchase)), Decimal(str(price)), value, updated,
            ]
        )
    if warehouse_id:
        warehouse_label = rows[0][4] if rows else warehouse_id
    return ReportTable(
        title="Informe de inventario",
        subtitle="Existencias físicas, reservadas y disponibles valoradas a precio de compra.",
        headers=INVENTORY_HEADERS,
        rows=data,
        formats=INVENTORY_FORMATS,
        totals=[
            "Total", "", "", "", "", "", "",
            total_qty, total_reserved, total_available, "", "", total_value, "",
        ],
        meta=[
            ("Almacén", warehouse_label if warehouse_id else "Todos"),
            ("Solo existencias positivas", "Sí" if only_positive else "No"),
        ],
        sheet_name="Inventario",
    )


def movements_table(
    db: Session, date_from: datetime | None, date_to: datetime | None
) -> ReportTable:
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

    location_codes = {loc.id: loc.full_code for loc in db.scalars(select(Location)).all()}
    data = [
        [
            reference,
            created,
            MOVEMENT_LABELS.get(mtype, str(mtype)),
            str(status),
            sku,
            name,
            Decimal(str(qty)),
            location_codes.get(from_id, ""),
            location_codes.get(to_id, ""),
            batch or "",
            reason or "",
            document_ref or "",
            "Sí" if confirmed else "No",
        ]
        for reference, created, mtype, status, sku, name, qty, from_id, to_id, batch, reason, document_ref, confirmed in rows
    ]
    period = "Sin límite"
    if date_from or date_to:
        start = date_from.strftime("%d/%m/%Y") if date_from else "inicio"
        finish = date_to.strftime("%d/%m/%Y") if date_to else "hoy"
        period = f"{start} – {finish}"
    return ReportTable(
        title="Libro de movimientos",
        subtitle="Entradas, salidas, movimientos internos y ajustes confirmados.",
        headers=MOVEMENT_HEADERS,
        rows=data,
        formats=MOVEMENT_FORMATS,
        meta=[("Periodo", period)],
        sheet_name="Movimientos",
    )


def table_csv_bytes(table: ReportTable) -> bytes:
    """CSV UTF-8 con BOM y separador ``;`` (el formato que ya abre Excel)."""
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(table.headers)
    writer.writerows(table_as_csv_rows(table))
    return buffer.getvalue().encode("utf-8")
