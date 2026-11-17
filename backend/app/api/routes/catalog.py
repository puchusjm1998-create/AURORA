"""Suppliers, products, stock levels and barcode/QR resolution."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.api.serializers import (
    build_stock_summaries,
    product_to_read,
    products_to_read,
    stock_level_to_read,
)
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Invoice,
    InvoiceLine,
    Location,
    Pallet,
    Product,
    ProductUnit,
    StockLevel,
    Supplier,
    User,
)
from app.schemas import (
    Message,
    Page,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    ProductWhereabouts,
    ScanResult,
    StockLevelRead,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
    UnitRead,
)
from app.services.audit import record_audit
from app.services.sequences import next_code
from app.services.stock import StockEngine

router = APIRouter(tags=["Catálogo e inventario"])


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
@router.get("/suppliers", response_model=Page[SupplierRead], summary="Listar proveedores")
def list_suppliers(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    search: str | None = None,
    include_inactive: bool = False,
) -> Page[SupplierRead]:
    stmt = select(Supplier).order_by(Supplier.name)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(or_(Supplier.name.ilike(term), Supplier.tax_id.ilike(term)))
    if not include_inactive:
        stmt = stmt.where(Supplier.is_active.is_(True))
    suppliers = list(db.scalars(stmt).all())
    items = [SupplierRead.model_validate(s) for s in suppliers]
    return Page(items=items, total=len(items), limit=len(items), offset=0)


@router.post("/suppliers", response_model=SupplierRead, status_code=201, summary="Crear proveedor")
def create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVENTORY_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> SupplierRead:
    if db.scalars(select(Supplier).where(Supplier.name == payload.name)).first():
        raise ConflictError("Ya existe un proveedor con ese nombre.")
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="supplier.created",
        entity_type="supplier",
        entity_id=supplier.id,
        after=payload.model_dump(),
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(supplier)
    return SupplierRead.model_validate(supplier)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierRead, summary="Modificar proveedor")
def update_supplier(
    supplier_id: str,
    payload: SupplierUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVENTORY_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> SupplierRead:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundError("Proveedor", supplier_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(supplier, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="supplier.updated",
        entity_type="supplier",
        entity_id=supplier.id,
        after=changes,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(supplier)
    return SupplierRead.model_validate(supplier)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@router.get("/products", response_model=Page[ProductRead], summary="Buscar productos")
def list_products(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    search: str | None = Query(None, description="SKU, nombre, referencia, código de barras o factura"),
    category: str | None = None,
    supplier_id: str | None = None,
    invoice_number: str | None = None,
    location_code: str | None = None,
    tracking_mode: str | None = None,
    is_active: bool | None = None,
    low_stock: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ProductRead]:
    stmt = select(Product)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Product.sku.ilike(term),
                Product.name.ilike(term),
                Product.manufacturer_ref.ilike(term),
                Product.barcode.ilike(term),
                Product.supplier_id.in_(
                    select(Supplier.id).where(Supplier.name.ilike(term))
                ),
            )
        )
    if category:
        stmt = stmt.where(Product.category == category)
    if supplier_id:
        stmt = stmt.where(Product.supplier_id == supplier_id)
    if tracking_mode:
        stmt = stmt.where(Product.tracking_mode == tracking_mode)
    if is_active is not None:
        stmt = stmt.where(Product.is_active.is_(is_active))
    if invoice_number:
        stmt = stmt.where(
            Product.id.in_(
                select(InvoiceLine.product_id)
                .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                .where(Invoice.number.ilike(f"%{invoice_number}%"))
            )
        )
    if location_code:
        stmt = stmt.where(
            Product.id.in_(
                select(StockLevel.product_id)
                .join(Location, Location.id == StockLevel.location_id)
                .where(Location.full_code == location_code.upper())
            )
        )
    if low_stock:
        stock_subq = (
            select(StockLevel.product_id, func.coalesce(func.sum(StockLevel.quantity), 0).label("qty"))
            .group_by(StockLevel.product_id)
            .subquery()
        )
        stmt = stmt.outerjoin(stock_subq, stock_subq.c.product_id == Product.id).where(
            func.coalesce(stock_subq.c.qty, 0) <= Product.min_stock,
            Product.min_stock > 0,
        )

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.scalar(total_stmt) or 0)
    products = list(db.scalars(stmt.order_by(Product.name).limit(limit).offset(offset)).all())
    return Page(items=products_to_read(db, products), total=total, limit=limit, offset=offset)


@router.get("/products/facets", summary="Categorías y proveedores para filtros")
def product_facets(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> dict:
    categories = db.execute(
        select(Product.category, func.count(Product.id))
        .where(Product.is_active.is_(True))
        .group_by(Product.category)
        .order_by(Product.category)
    ).all()
    suppliers = db.execute(
        select(Supplier.id, Supplier.name, func.count(Product.id))
        .join(Product, Product.supplier_id == Supplier.id, isouter=True)
        .where(Supplier.is_active.is_(True))
        .group_by(Supplier.id, Supplier.name)
        .order_by(Supplier.name)
    ).all()
    return {
        "categories": [{"name": name, "count": int(count)} for name, count in categories],
        "suppliers": [
            {"id": supplier_id, "name": name, "count": int(count)}
            for supplier_id, name, count in suppliers
        ],
    }


@router.post("/products", response_model=ProductRead, status_code=201, summary="Crear producto")
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVENTORY_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ProductRead:
    sku = (payload.sku or next_code(db, "product")).strip().upper()
    if db.scalars(select(Product).where(Product.sku == sku)).first():
        raise ConflictError(f"Ya existe un producto con el SKU {sku}.")
    if payload.supplier_id and db.get(Supplier, payload.supplier_id) is None:
        raise NotFoundError("Proveedor", payload.supplier_id)
    data = payload.model_dump(exclude={"sku"})
    product = Product(sku=sku, **data)
    db.add(product)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="product.created",
        entity_type="product",
        entity_id=product.id,
        after={"sku": sku, "name": product.name, "tracking_mode": product.tracking_mode},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(product)
    return product_to_read(db, product)


@router.get("/products/by-sku/{sku}", response_model=ProductRead, summary="Producto por SKU")
def get_product_by_sku(
    sku: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> ProductRead:
    product = db.scalars(select(Product).where(Product.sku == sku.upper())).first()
    if product is None:
        raise NotFoundError("Producto", sku)
    return product_to_read(db, product)


@router.get("/products/{product_id}", response_model=ProductRead, summary="Consultar producto")
def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> ProductRead:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Producto", product_id)
    return product_to_read(db, product)


@router.patch("/products/{product_id}", response_model=ProductRead, summary="Modificar producto")
def update_product(
    product_id: str,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVENTORY_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ProductRead:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Producto", product_id)
    changes = payload.model_dump(exclude_unset=True)
    if "supplier_id" in changes and changes["supplier_id"]:
        if db.get(Supplier, changes["supplier_id"]) is None:
            raise NotFoundError("Proveedor", changes["supplier_id"])
    before = {key: getattr(product, key) for key in changes}
    for field, value in changes.items():
        setattr(product, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="product.updated",
        entity_type="product",
        entity_id=product.id,
        before=before,
        after=changes,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(product)
    return product_to_read(db, product)


@router.delete("/products/{product_id}", response_model=Message, summary="Desactivar producto")
def deactivate_product(
    product_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVENTORY_DELETE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Producto", product_id)
    if not product.is_active:
        return Message(message="El producto ya estaba desactivado.")
    engine = StockEngine(db)
    if engine.available(product.id) > 0:
        raise ValidationError("No se puede desactivar un producto con existencias. Dé de baja el stock primero.")
    product.is_active = False
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="product.deactivated",
        entity_type="product",
        entity_id=product.id,
        after={"sku": product.sku},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    return Message(message=f"Producto {product.sku} desactivado. El histórico se conserva.")


@router.get("/products/{product_id}/whereabouts", response_model=ProductWhereabouts, summary="Localización exacta")
def product_whereabouts(
    product_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> ProductWhereabouts:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Producto", product_id)
    levels = list(
        db.scalars(
            select(StockLevel)
            .where(StockLevel.product_id == product_id, StockLevel.quantity > 0)
            .order_by(StockLevel.quantity.desc())
        ).all()
    )
    summary = build_stock_summaries(db, [product_id]).get(product_id)
    return ProductWhereabouts(
        product=product_to_read(db, product, summary),
        stock=summary,
        positions=[stock_level_to_read(level) for level in levels],
    )


@router.get("/products/{product_id}/units", response_model=Page[UnitRead], summary="Unidades individuales")
def product_units(
    product_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[UnitRead]:
    if db.get(Product, product_id) is None:
        raise NotFoundError("Producto", product_id)
    stmt = select(ProductUnit).where(ProductUnit.product_id == product_id)
    if status:
        stmt = stmt.where(ProductUnit.status == status)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    units = list(db.scalars(stmt.order_by(ProductUnit.code).limit(limit).offset(offset)).all())
    items = [
        UnitRead(
            id=unit.id,
            code=unit.code,
            product_id=unit.product_id,
            serial_number=unit.serial_number,
            batch_code=unit.batch_code,
            status=unit.status,
            pallet_code=unit.pallet.code if unit.pallet else None,
            location_code=unit.location.full_code if unit.location else None,
            created_at=unit.created_at,
        )
        for unit in units
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Stock levels
# ---------------------------------------------------------------------------
@router.get("/stock/levels", response_model=Page[StockLevelRead], summary="Existencias por ubicación")
def list_stock_levels(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    product_id: str | None = None,
    location_id: str | None = None,
    pallet_id: str | None = None,
    warehouse_id: str | None = None,
    only_positive: bool = True,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[StockLevelRead]:
    stmt = select(StockLevel)
    if product_id:
        stmt = stmt.where(StockLevel.product_id == product_id)
    if location_id:
        stmt = stmt.where(StockLevel.location_id == location_id)
    if pallet_id:
        stmt = stmt.where(StockLevel.pallet_id == pallet_id)
    if warehouse_id:
        stmt = stmt.join(Location, Location.id == StockLevel.location_id).where(
            Location.warehouse_id == warehouse_id
        )
    if only_positive:
        stmt = stmt.where(StockLevel.quantity > 0)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    levels = list(db.scalars(stmt.order_by(StockLevel.updated_at.desc()).limit(limit).offset(offset)).all())
    return Page(items=[stock_level_to_read(lvl) for lvl in levels], total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# QR resolution (scan from mobile camera or manual entry)
# ---------------------------------------------------------------------------
@router.get("/scan/resolve", response_model=ScanResult, summary="Resolver código escaneado")
def resolve_scan(
    code: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> ScanResult:
    raw = code.strip()
    if raw.startswith("aurora://"):
        raw = raw[len("aurora://"):]
        if "/" not in raw:
            raise ValidationError("Código QR no reconocido.")
        kind, value = raw.split("/", 1)
    else:
        kind, value = "", raw

    value = value.strip()
    if kind == "location" or (not kind and "-" in value and value.startswith("ALM-")):
        location = db.scalars(select(Location).where(Location.full_code == value.upper())).first()
        if location:
            return ScanResult(
                kind="location",
                code=location.full_code,
                title=location.full_code,
                subtitle=f"{location.warehouse.code} · {location.label}" if location.label else location.warehouse.code,
                target_type="location",
                target_id=location.id,
                href=f"/ubicacion?id={location.id}",
                extra={
                    "capacidad_palets": location.capacity_pallets,
                    "pasillo": location.aisle,
                    "estanteria": location.rack,
                    "nivel": location.level,
                    "posicion": location.position,
                },
            )
    if kind == "pallet" or (not kind and value.upper().startswith("AUR-PAL-")):
        pallet = db.scalars(select(Pallet).where(Pallet.code == value.upper())).first()
        if pallet:
            return ScanResult(
                kind="pallet",
                code=pallet.code,
                title=pallet.code,
                subtitle=f"{len(pallet.items)} referencias · {pallet.status.value}",
                target_type="pallet",
                target_id=pallet.id,
                href=f"/pale?id={pallet.id}",
                extra={"status": pallet.status.value, "location": pallet.location.full_code if pallet.location else None},
            )
    if kind == "unit" or (not kind and value.upper().startswith("AUR-OBJ-")):
        unit = db.scalars(select(ProductUnit).where(ProductUnit.code == value.upper())).first()
        if unit:
            return ScanResult(
                kind="unit",
                code=unit.code,
                title=f"{unit.product.name}",
                subtitle=unit.serial_number or unit.code,
                target_type="unit",
                target_id=unit.id,
                href=f"/producto?id={unit.product_id}",
                extra={
                    "status": unit.status.value,
                    "product_sku": unit.product.sku,
                    "pallet": unit.pallet.code if unit.pallet else None,
                    "location": unit.location.full_code if unit.location else None,
                },
            )
    if kind == "product" or not kind:
        product = db.scalars(
            select(Product).where(
                or_(Product.sku == value.upper(), Product.barcode == value)
            )
        ).first()
        if product:
            summary = build_stock_summaries(db, [product.id]).get(product.id)
            return ScanResult(
                kind="product",
                code=product.sku,
                title=product.name,
                subtitle=f"{product.sku} · disponible {summary.available if summary else 0} {product.uom}",
                target_type="product",
                target_id=product.id,
                href=f"/producto?id={product.id}",
                extra={"tracking_mode": product.tracking_mode.value},
            )
    if kind == "employee" or (not kind and value.upper().startswith("AUR-EMP-")):
        from app.models import Employee

        employee = db.scalars(select(Employee).where(Employee.code == value.upper())).first()
        if employee:
            return ScanResult(
                kind="employee",
                code=employee.code,
                title=employee.full_name,
                subtitle=f"{employee.position} · {employee.department}",
                target_type="employee",
                target_id=employee.id,
                href="/personal",
                extra={"status": employee.status.value},
            )
    raise NotFoundError("Código", code)


@router.get("/scan/parse", response_model=Message, summary="Validar formato de QR")
def parse_qr(code: str) -> Message:
    from app.services.qr import parse_payload

    parsed = parse_payload(code)
    if parsed is None:
        raise ValidationError("El contenido no es un código AURORA válido.")
    return Message(message="Código válido", details={"kind": parsed[0], "code": parsed[1]})
