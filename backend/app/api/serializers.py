"""ORM -> API schema conversions, including computed stock figures."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Employee,
    Invoice,
    Location,
    Pallet,
    Product,
    ProductUnit,
    StockLevel,
    StockMovement,
    User,
)
from app.schemas import (
    EmployeeBrief,
    EmployeeRead,
    InvoiceLineRead,
    InvoiceRead,
    LocationRead,
    MovementAllocationRead,
    MovementRead,
    PalletItemRead,
    PalletRead,
    ProductRead,
    StockLevelRead,
    StockSummary,
    SupplierBrief,
    UserRead,
)

ZERO = Decimal("0")


def _dec(value: Decimal | None) -> Decimal:
    return value if value is not None else ZERO


def build_stock_summaries(db: Session, product_ids: list[str]) -> dict[str, StockSummary]:
    if not product_ids:
        return {}
    levels = db.execute(
        select(
            StockLevel.product_id,
            func.coalesce(func.sum(StockLevel.quantity), 0),
            func.coalesce(func.sum(StockLevel.reserved_quantity), 0),
            func.count(func.distinct(StockLevel.location_id)),
        )
        .where(StockLevel.product_id.in_(product_ids))
        .group_by(StockLevel.product_id)
    ).all()
    summaries: dict[str, StockSummary] = {}
    for product_id, on_hand, reserved, locations in levels:
        summaries[product_id] = StockSummary(
            on_hand=Decimal(str(on_hand)),
            reserved=Decimal(str(reserved)),
            available=Decimal(str(on_hand)) - Decimal(str(reserved)),
            locations=int(locations),
            in_transit=ZERO,
            value=ZERO,
        )

    units = db.execute(
        select(ProductUnit.product_id, func.count(ProductUnit.id))
        .where(ProductUnit.product_id.in_(product_ids), ProductUnit.status == "in_stock")
        .group_by(ProductUnit.product_id)
    ).all()
    for product_id, count in units:
        summaries.setdefault(product_id, StockSummary()).unit_count = int(count)

    # In transit: quantity invoiced but not yet received.
    from app.models import InvoiceLine

    transit = db.execute(
        select(
            InvoiceLine.product_id,
            func.coalesce(func.sum(InvoiceLine.quantity - InvoiceLine.received_quantity), 0),
        )
        .where(
            InvoiceLine.product_id.in_(product_ids),
            InvoiceLine.quantity > InvoiceLine.received_quantity,
        )
        .group_by(InvoiceLine.product_id)
    ).all()
    for product_id, pending in transit:
        if product_id in summaries:
            summaries[product_id].in_transit = Decimal(str(pending))

    prices = db.execute(
        select(Product.id, Product.purchase_price).where(Product.id.in_(product_ids))
    ).all()
    for product_id, price in prices:
        summary = summaries.setdefault(product_id, StockSummary())
        summary.value = (summary.on_hand * _dec(price)).quantize(Decimal("0.01"))
    return summaries


def product_to_read(db: Session, product: Product, summary: StockSummary | None = None) -> ProductRead:
    summary = summary or build_stock_summaries(db, [product.id]).get(product.id, StockSummary())
    data = ProductRead.model_validate(product)
    data.stock = summary
    return data


def products_to_read(db: Session, products: Iterable[Product]) -> list[ProductRead]:
    product_list = list(products)
    summaries = build_stock_summaries(db, [p.id for p in product_list])
    result = []
    for product in product_list:
        data = ProductRead.model_validate(product)
        data.stock = summaries.get(product.id, StockSummary())
        result.append(data)
    return result


def employee_brief(employee: Employee | None) -> EmployeeBrief | None:
    if employee is None:
        return None
    return EmployeeBrief(
        id=employee.id,
        code=employee.code,
        first_name=employee.first_name,
        last_name=employee.last_name,
        department=employee.department,
        position=employee.position,
    )


def user_to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role_id=user.role_id,
        role_level=user.role.level,
        role_name=user.role.name,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        employee=employee_brief(user.employee),
    )


def employee_to_read(employee: Employee) -> EmployeeRead:
    return EmployeeRead(
        id=employee.id,
        code=employee.code,
        first_name=employee.first_name,
        last_name=employee.last_name,
        department=employee.department,
        position=employee.position,
        status=employee.status,
        hire_date=employee.hire_date,
        phone=employee.phone,
        weekly_hours=employee.weekly_hours,
        user_id=employee.user_id,
        created_at=employee.created_at,
    )


def location_to_read(
    db: Session,
    location: Location,
    occupied_pallets: int | None = None,
    occupied_units: Decimal | None = None,
) -> LocationRead:
    if occupied_pallets is None or occupied_units is None:
        pallets = db.scalar(
            select(func.count(Pallet.id)).where(
                Pallet.location_id == location.id,
                Pallet.status.in_(["open", "sealed"]),
            )
        )
        units = db.scalar(
            select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(
                StockLevel.location_id == location.id
            )
        )
        occupied_pallets = int(pallets or 0)
        occupied_units = Decimal(str(units or 0))
    return LocationRead(
        id=location.id,
        warehouse_id=location.warehouse_id,
        warehouse_code=location.warehouse.code if location.warehouse else None,
        full_code=location.full_code,
        aisle=location.aisle,
        rack=location.rack,
        level=location.level,
        position=location.position,
        label=location.label,
        capacity_pallets=location.capacity_pallets,
        capacity_units=location.capacity_units,
        is_pick_face=location.is_pick_face,
        is_active=location.is_active,
        occupied_pallets=occupied_pallets,
        occupied_units=occupied_units,
    )


def stock_level_to_read(level: StockLevel) -> StockLevelRead:
    return StockLevelRead(
        id=level.id,
        product_id=level.product_id,
        product_sku=level.product.sku,
        product_name=level.product.name,
        uom=level.product.uom,
        location_id=level.location_id,
        quantity=level.quantity,
        reserved_quantity=level.reserved_quantity,
        available_quantity=level.quantity - level.reserved_quantity,
        location_code=level.location.full_code,
        location_label=level.location.label,
        warehouse_code=level.location.warehouse.code,
        warehouse_name=level.location.warehouse.name,
        pallet_id=level.pallet_id,
        pallet_code=level.pallet.code if level.pallet else None,
        aisle=level.location.aisle,
        rack=level.location.rack,
        level=level.location.level,
        position=level.location.position,
        updated_at=level.updated_at,
    )


def pallet_to_read(pallet: Pallet) -> PalletRead:
    items = [
        PalletItemRead(
            id=item.id,
            product_id=item.product_id,
            quantity=item.quantity,
            batch_code=item.batch_code,
            product=ProductRead.model_validate(item.product),
        )
        for item in pallet.items
    ]
    total = sum((item.quantity for item in pallet.items), ZERO)
    return PalletRead(
        id=pallet.id,
        code=pallet.code,
        status=pallet.status,
        warehouse_id=pallet.warehouse_id,
        warehouse_code=pallet.warehouse.code,
        location_id=pallet.location_id,
        location_code=pallet.location.full_code if pallet.location else None,
        invoice_id=pallet.invoice_id,
        notes=pallet.notes,
        gross_weight_kg=pallet.gross_weight_kg,
        item_count=len(items),
        total_units=total,
        sealed_at=pallet.sealed_at,
        created_at=pallet.created_at,
        items=items,
    )


def movement_to_read(db: Session, movement: StockMovement, user_names: dict[str, str] | None = None) -> MovementRead:
    creator_name = None
    if movement.created_by:
        if user_names is not None:
            creator_name = user_names.get(movement.created_by)
        else:
            creator = db.get(User, movement.created_by)
            creator_name = creator.full_name if creator else None

    return MovementRead(
        id=movement.id,
        reference=movement.reference,
        movement_type=movement.movement_type,
        status=movement.status,
        product_id=movement.product_id,
        product_sku=movement.product.sku,
        product_name=movement.product.name,
        uom=movement.product.uom,
        quantity=movement.quantity,
        batch_code=movement.batch_code,
        from_location_id=movement.from_location_id,
        from_location_code=movement.from_location.full_code if movement.from_location else None,
        to_location_id=movement.to_location_id,
        to_location_code=movement.to_location.full_code if movement.to_location else None,
        from_pallet_id=movement.from_pallet_id,
        from_pallet_code=None,
        to_pallet_id=movement.to_pallet_id,
        to_pallet_code=None,
        worker_id=movement.worker_id,
        worker_name=movement.worker.full_name if movement.worker else None,
        reason=movement.reason,
        document_ref=movement.document_ref,
        invoice_id=movement.invoice_id,
        physical_confirmed=movement.physical_confirmed,
        confirmed_at=movement.confirmed_at,
        created_at=movement.created_at,
        created_by=movement.created_by,
        created_by_name=creator_name,
        allocations=[
            MovementAllocationRead(
                location_code=allocation.location.full_code,
                pallet_code=allocation.pallet.code if allocation.pallet else None,
                quantity=allocation.quantity,
            )
            for allocation in movement.allocations
        ],
        unit_codes=[link.unit.code for link in movement.units],
    )


def invoice_to_read(invoice: Invoice) -> InvoiceRead:
    return InvoiceRead(
        id=invoice.id,
        number=invoice.number,
        supplier_id=invoice.supplier_id,
        supplier_name=invoice.supplier.name if invoice.supplier else None,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        subtotal=invoice.subtotal,
        tax_total=invoice.tax_total,
        total=invoice.total,
        currency=invoice.currency,
        status=invoice.status,
        ocr_status=invoice.ocr_status.value if hasattr(invoice.ocr_status, "value") else str(invoice.ocr_status),
        original_filename=invoice.original_filename,
        mime_type=invoice.mime_type,
        file_path=invoice.file_path,
        file_sha256=invoice.file_sha256,
        notes=invoice.notes,
        created_at=invoice.created_at,
        reconciled_at=invoice.reconciled_at,
        lines=[
            InvoiceLineRead(
                id=line.id,
                line_number=line.line_number,
                product_id=line.product_id,
                supplier_ref=line.supplier_ref,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_pct=line.discount_pct,
                tax_rate=line.tax_rate,
                line_total=line.line_total,
                received_quantity=line.received_quantity,
                review_required=line.review_required,
                product_sku=line.product.sku if line.product else None,
                product_name=line.product.name if line.product else None,
            )
            for line in sorted(invoice.lines, key=lambda l: l.line_number)
        ],
    )
