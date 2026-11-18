"""Datos de los informes reutilizables por la API, el correo y los scripts.

Una única consulta alimenta las exportaciones CSV, PDF y Excel, tanto las
descargas manuales como los envíos programados.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
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


INVOICE_HEADERS = [
    "Número", "Proveedor", "Fecha", "Vencimiento", "Estado", "Origen",
    "Moneda", "Base", "IVA", "Total", "Líneas", "Conciliada", "SHA-256",
]
INVOICE_FORMATS = {7: "money", 8: "money", 9: "money", 10: "int"}

DELIVERY_HEADERS = [
    "Referencia", "Estado", "Destino", "Dirección", "Vehículo", "Conductor",
    "Salida prevista", "Salida real", "Entrega", "Palés", "Firma", "Creado",
]
DELIVERY_FORMATS = {9: "int"}

EMPLOYEE_HEADERS = [
    "Código", "Nombre", "Departamento", "Puesto", "Jornada semanal",
    "Estado", "Alta", "Teléfono", "Usuario",
]
EMPLOYEE_FORMATS = {4: "money"}

INVOICE_STATUS_LABELS = {
    "received": "Recibida",
    "in_review": "En revisión",
    "reconciled": "Conciliada",
    "discrepancy": "Con diferencias",
}
DELIVERY_STATUS_LABELS = {
    "draft": "Borrador",
    "preparing": "Preparando",
    "ready": "Lista",
    "loaded": "Cargada",
    "in_transit": "En tránsito",
    "delivered": "Entregada",
    "failed": "Fallida",
    "returned": "Devuelta",
    "cancelled": "Cancelada",
}
EMPLOYEE_STATUS_LABELS = {
    "active": "Activo",
    "inactive": "Inactivo",
    "on_leave": "Baja temporal",
}


def invoices_table(
    db: Session,
    date_from: date | None,
    date_to: date | None,
    status: str | None = None,
) -> ReportTable:
    from app.models import Invoice, InvoiceLine, Supplier

    line_count = (
        select(InvoiceLine.invoice_id, func.count(InvoiceLine.id).label("lines"))
        .group_by(InvoiceLine.invoice_id)
        .subquery()
    )
    stmt = (
        select(
            Invoice.number,
            Supplier.name,
            Invoice.invoice_date,
            Invoice.due_date,
            Invoice.status,
            Invoice.source,
            Invoice.currency,
            Invoice.subtotal,
            Invoice.tax_total,
            Invoice.total,
            func.coalesce(line_count.c.lines, 0),
            Invoice.reconciled_at,
            Invoice.file_sha256,
        )
        .outerjoin(Supplier, Supplier.id == Invoice.supplier_id)
        .outerjoin(line_count, line_count.c.invoice_id == Invoice.id)
    )
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if status:
        stmt = stmt.where(Invoice.status == status)
    rows = db.execute(stmt.order_by(Invoice.invoice_date.desc(), Invoice.number)).all()

    data: list[list] = []
    total_base = total_tax = total_total = Decimal("0")
    for (
        number, supplier, issued, due, state, source, currency,
        subtotal, tax, total, lines, reconciled, digest,
    ) in rows:
        base = Decimal(str(subtotal))
        tax_value = Decimal(str(tax))
        total_value = Decimal(str(total))
        total_base += base
        total_tax += tax_value
        total_total += total_value
        data.append(
            [
                number,
                supplier or "Sin proveedor",
                issued,
                due or "",
                INVOICE_STATUS_LABELS.get(str(state), str(state)),
                "Subida" if str(source) == "upload" else "Manual",
                currency,
                base,
                tax_value,
                total_value,
                int(lines or 0),
                "Sí" if reconciled else "No",
                digest or "",
            ]
        )
    period = _period_label(date_from, date_to)
    return ReportTable(
        title="Facturación y conciliaciones",
        subtitle="Facturas recibidas, importes, estado de revisión y conciliación.",
        headers=INVOICE_HEADERS,
        rows=data,
        formats=INVOICE_FORMATS,
        totals=[
            "Total", "", "", "", "", "", "",
            total_base, total_tax, total_total, "", "", "",
        ],
        meta=[
            ("Periodo de factura", period),
            ("Estado", INVOICE_STATUS_LABELS.get(status or "", "Todos")),
            ("Facturas", str(len(data))),
        ],
        sheet_name="Facturas",
    )


def deliveries_table(
    db: Session,
    date_from: datetime | None,
    date_to: datetime | None,
    status: str | None = None,
) -> ReportTable:
    from app.models import Delivery, DeliveryPallet, DeliverySignature, Employee, Vehicle

    pallet_count = (
        select(
            DeliveryPallet.delivery_id,
            func.count(DeliveryPallet.id).label("pallets"),
        )
        .group_by(DeliveryPallet.delivery_id)
        .subquery()
    )
    signature_count = (
        select(
            DeliverySignature.delivery_id,
            func.count(DeliverySignature.id).label("signatures"),
        )
        .group_by(DeliverySignature.delivery_id)
        .subquery()
    )
    stmt = (
        select(
            Delivery.reference,
            Delivery.status,
            Delivery.destination_name,
            Delivery.destination_address,
            Vehicle.plate,
            Employee.first_name,
            Employee.last_name,
            Delivery.planned_departure,
            Delivery.departed_at,
            Delivery.delivered_at,
            func.coalesce(pallet_count.c.pallets, 0),
            func.coalesce(signature_count.c.signatures, 0),
            Delivery.created_at,
        )
        .outerjoin(Vehicle, Vehicle.id == Delivery.vehicle_id)
        .outerjoin(Employee, Employee.id == Delivery.driver_employee_id)
        .outerjoin(pallet_count, pallet_count.c.delivery_id == Delivery.id)
        .outerjoin(signature_count, signature_count.c.delivery_id == Delivery.id)
    )
    if date_from:
        stmt = stmt.where(Delivery.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Delivery.created_at <= date_to)
    if status:
        stmt = stmt.where(Delivery.status == status)
    rows = db.execute(stmt.order_by(Delivery.created_at.desc())).all()

    data = [
        [
            reference,
            DELIVERY_STATUS_LABELS.get(str(state), str(state)),
            destination,
            address or "",
            plate or "",
            " ".join(part for part in (first, last) if part) or "",
            planned or "",
            departed or "",
            delivered or "",
            int(pallets or 0),
            "Sí" if signatures else "No",
            created,
        ]
        for (
            reference, state, destination, address, plate, first, last,
            planned, departed, delivered, pallets, signatures, created,
        ) in rows
    ]
    return ReportTable(
        title="Repartos y entregas",
        subtitle="Expediciones, conductor, vehículo, palés, firma y estado de entrega.",
        headers=DELIVERY_HEADERS,
        rows=data,
        formats=DELIVERY_FORMATS,
        meta=[
            ("Periodo de creación", _period_label(date_from, date_to)),
            ("Estado", DELIVERY_STATUS_LABELS.get(status or "", "Todos")),
            ("Repartos", str(len(data))),
        ],
        sheet_name="Repartos",
    )


def employees_table(db: Session, active_only: bool = False) -> ReportTable:
    from app.models import Employee, User

    stmt = select(
        Employee.code,
        Employee.first_name,
        Employee.last_name,
        Employee.department,
        Employee.position,
        Employee.weekly_hours,
        Employee.status,
        Employee.hire_date,
        Employee.phone,
        User.email,
    ).outerjoin(User, User.id == Employee.user_id)
    if active_only:
        stmt = stmt.where(Employee.status == "active")
    rows = db.execute(stmt.order_by(Employee.last_name, Employee.first_name)).all()
    data = [
        [
            code,
            f"{first} {last}".strip(),
            department or "",
            position or "",
            Decimal(str(hours)),
            EMPLOYEE_STATUS_LABELS.get(str(state), str(state)),
            hired or "",
            phone or "",
            email or "",
        ]
        for code, first, last, department, position, hours, state, hired, phone, email in rows
    ]
    total_hours = sum((Decimal(str(row[4])) for row in data), Decimal("0"))
    return ReportTable(
        title="Plantilla y jornada",
        subtitle="Trabajadores, puesto, contrato semanal, estado y cuenta vinculada.",
        headers=EMPLOYEE_HEADERS,
        rows=data,
        formats=EMPLOYEE_FORMATS,
        totals=["Total", "", "", "", total_hours, "", "", "", ""],
        meta=[
            ("Solo activos", "Sí" if active_only else "No"),
            ("Trabajadores", str(len(data))),
        ],
        sheet_name="Plantilla",
    )


def _period_label(
    date_from: date | datetime | None, date_to: date | datetime | None
) -> str:
    if not date_from and not date_to:
        return "Sin límite"
    start = date_from.strftime("%d/%m/%Y") if date_from else "inicio"
    finish = date_to.strftime("%d/%m/%Y") if date_to else "hoy"
    return f"{start} – {finish}"
