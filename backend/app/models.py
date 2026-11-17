"""SQLAlchemy ORM models for AURORA LOGISTICS AI.

The schema is intentionally explicit and normalised:

* ``users``/``roles``/``permissions`` implement server-side role based access control.
* ``warehouses`` -> ``locations`` model the physical hierarchy encoded in the
  location code (e.g. ``ALM-01-P04-EB-N02-POS03``).
* ``products`` -> ``pallets`` -> ``pallet_items`` -> ``product_units`` model
  quantity, batch and individual-unit tracking.
* ``stock_levels`` is the single source of truth for physical stock, always
  expressed as (product, location, optional pallet).
* ``stock_movements`` is the immutable ledger: stock is only changed by
  confirming a movement, inside a database transaction.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.enums import (
    AttendanceEventType,
    DeliveryStatus,
    EmployeeStatus,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    InvoiceSource,
    InvoiceStatus,
    MovementStatus,
    MovementType,
    OCRStatus,
    PalletStatus,
    ReservationStatus,
    TaskStatus,
    TrackingMode,
    UnitStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_cls: type, name: str, **kwargs: Any) -> SAEnum:
    return SAEnum(enum_cls, name=name, native_enum=False, length=32, validate_strings=True, **kwargs)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Code sequences (human-readable, non-reusable identifiers)
# ---------------------------------------------------------------------------
class CodeSequence(Base):
    __tablename__ = "code_sequences"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=6)


# ---------------------------------------------------------------------------
# Identity, roles and permissions
# ---------------------------------------------------------------------------
class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 5", name="role_level_range"),
        UniqueConstraint("level", name="uq_roles_level"),
    )


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="general", nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = relationship(back_populates="permissions")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship(lazy="joined")
    employee: Mapped[Optional["Employee"]] = relationship(back_populates="user", uselist=False)

    @property
    def role_level(self) -> int:
        return self.role.level


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)  # == JWT jti
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))

    user: Mapped[User] = relationship(lazy="joined")


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)  # AUR-EMP-000001
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    position: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    status: Mapped[EmployeeStatus] = mapped_column(
        enum_column(EmployeeStatus, "employee_status"), default=EmployeeStatus.ACTIVE, nullable=False
    )
    hire_date: Mapped[Optional[date]] = mapped_column(Date)
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)

    user: Mapped[Optional[User]] = relationship(back_populates="employee")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


# ---------------------------------------------------------------------------
# Physical warehouse structure
# ---------------------------------------------------------------------------
class Warehouse(Base, TimestampMixin):
    __tablename__ = "warehouses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # ALM-01
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    postal_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="ES", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Madrid", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    locations: Mapped[list["Location"]] = relationship(back_populates="warehouse")


class Location(Base, TimestampMixin):
    """A storage position inside a warehouse.

    Hierarchy: warehouse -> aisle (pasillo) -> rack (estantería) -> level (nivel)
    -> position. The concatenation forms the persistent location code.
    """

    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    warehouse_id: Mapped[str] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    aisle: Mapped[str] = mapped_column(String(16), nullable=False)
    rack: Mapped[str] = mapped_column(String(16), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[str] = mapped_column(String(16), nullable=False)
    full_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    capacity_pallets: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    capacity_units: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3))
    is_pick_face: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    warehouse: Mapped[Warehouse] = relationship(back_populates="locations", lazy="joined")

    __table_args__ = (CheckConstraint("capacity_pallets >= 0", name="capacity_non_negative"),)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    tax_id: Mapped[Optional[str]] = mapped_column(String(32))
    contact_name: Mapped[Optional[str]] = mapped_column(String(120))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    manufacturer_ref: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="General", nullable=False, index=True)
    supplier_id: Mapped[Optional[str]] = mapped_column(ForeignKey("suppliers.id"), index=True)
    uom: Mapped[str] = mapped_column(String(16), default="ud", nullable=False)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    min_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)
    tracking_mode: Mapped[TrackingMode] = mapped_column(
        enum_column(TrackingMode, "tracking_mode"), default=TrackingMode.QUANTITY, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    supplier: Mapped[Optional[Supplier]] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("purchase_price >= 0", name="purchase_price_non_negative"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    )


class ProductBatch(Base, TimestampMixin):
    __tablename__ = "product_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    batch_code: Mapped[str] = mapped_column(String(64), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)
    quantity_remaining: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)
    invoice_id: Mapped[Optional[str]] = mapped_column(ForeignKey("invoices.id"))

    __table_args__ = (UniqueConstraint("product_id", "batch_code", name="uq_batch_product_code"),)


class ProductUnit(Base, TimestampMixin):
    """A single physical item identified by its own non-reusable code (AUR-OBJ-*)."""

    __tablename__ = "product_units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(80))
    batch_code: Mapped[Optional[str]] = mapped_column(String(64))
    pallet_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pallets.id", ondelete="SET NULL"), index=True)
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), index=True)
    status: Mapped[UnitStatus] = mapped_column(
        enum_column(UnitStatus, "unit_status"), default=UnitStatus.IN_STOCK, nullable=False
    )
    invoice_id: Mapped[Optional[str]] = mapped_column(ForeignKey("invoices.id"))

    product: Mapped[Product] = relationship(lazy="joined")
    pallet: Mapped[Optional["Pallet"]] = relationship(lazy="joined")
    location: Mapped[Optional[Location]] = relationship(lazy="joined", foreign_keys=[location_id])


# ---------------------------------------------------------------------------
# Pallets and stock
# ---------------------------------------------------------------------------
class Pallet(Base, TimestampMixin):
    __tablename__ = "pallets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)  # AUR-PAL-000001
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"), index=True)
    status: Mapped[PalletStatus] = mapped_column(
        enum_column(PalletStatus, "pallet_status"), default=PalletStatus.OPEN, nullable=False
    )
    invoice_id: Mapped[Optional[str]] = mapped_column(ForeignKey("invoices.id"))
    gross_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sealed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    warehouse: Mapped[Warehouse] = relationship(lazy="joined")
    location: Mapped[Optional[Location]] = relationship(lazy="joined")
    items: Mapped[list["PalletItem"]] = relationship(
        back_populates="pallet", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("gross_weight_kg IS NULL OR gross_weight_kg >= 0", name="weight_non_negative"),
    )


class PalletItem(Base, TimestampMixin):
    __tablename__ = "pallet_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pallet_id: Mapped[str] = mapped_column(ForeignKey("pallets.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    batch_code: Mapped[Optional[str]] = mapped_column(String(64))

    pallet: Mapped[Pallet] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class StockLevel(Base):
    """Current physical stock for a (product, location, pallet) tuple."""

    __tablename__ = "stock_levels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), index=True)
    pallet_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pallets.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    product: Mapped[Product] = relationship(lazy="joined")
    location: Mapped[Location] = relationship(lazy="joined")
    pallet: Mapped[Optional[Pallet]] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_non_negative"),
        CheckConstraint("reserved_quantity <= quantity", name="reserved_not_above_quantity"),
        UniqueConstraint("product_id", "location_id", "pallet_id", name="uq_stock_product_location_pallet"),
        Index(
            "uq_stock_product_location_no_pallet",
            "product_id",
            "location_id",
            unique=True,
            sqlite_where=text("pallet_id IS NULL"),
            postgresql_where=text("pallet_id IS NULL"),
        ),
    )


class StockReservation(Base, TimestampMixin):
    __tablename__ = "stock_reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"))
    pallet_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pallets.id", ondelete="SET NULL"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        enum_column(ReservationStatus, "reservation_status"),
        default=ReservationStatus.ACTIVE,
        nullable=False,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    product: Mapped[Product] = relationship(lazy="joined")
    location: Mapped[Location] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("quantity > 0", name="reservation_quantity_positive"),)


class StockMovement(Base):
    """Immutable ledger of every stock change.

    Rows are inserted once. ``status`` only moves forward (draft -> confirmed or
    cancelled); stock is applied at confirmation, inside one transaction.
    """

    __tablename__ = "stock_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    movement_type: Mapped[MovementType] = mapped_column(
        enum_column(MovementType, "movement_type"), nullable=False, index=True
    )
    status: Mapped[MovementStatus] = mapped_column(
        enum_column(MovementStatus, "movement_status"),
        default=MovementStatus.DRAFT,
        nullable=False,
        index=True,
    )
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    pallet_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pallets.id", ondelete="SET NULL"))
    from_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"))
    to_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"))
    from_pallet_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pallets.id", ondelete="SET NULL"))
    to_pallet_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pallets.id", ondelete="SET NULL"))
    worker_id: Mapped[Optional[str]] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    batch_code: Mapped[Optional[str]] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    document_ref: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    invoice_id: Mapped[Optional[str]] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    invoice_line_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("invoice_lines.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(80), unique=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    physical_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    physical_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    product: Mapped[Product] = relationship(lazy="joined")
    from_location: Mapped[Optional[Location]] = relationship(
        foreign_keys=[from_location_id], lazy="joined"
    )
    to_location: Mapped[Optional[Location]] = relationship(foreign_keys=[to_location_id], lazy="joined")
    worker: Mapped[Optional[Employee]] = relationship(lazy="joined")
    units: Mapped[list["MovementUnit"]] = relationship(
        back_populates="movement", cascade="all, delete-orphan", lazy="selectin"
    )
    allocations: Mapped[list["MovementAllocation"]] = relationship(
        back_populates="movement", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("quantity <> 0", name="movement_quantity_not_zero"),
    )


class MovementUnit(Base):
    """Links a movement to the individual units it affects (unit tracking mode)."""

    __tablename__ = "movement_units"

    movement_id: Mapped[str] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="CASCADE"), primary_key=True
    )
    unit_id: Mapped[str] = mapped_column(ForeignKey("product_units.id"), primary_key=True)

    movement: Mapped[StockMovement] = relationship(back_populates="units")
    unit: Mapped[ProductUnit] = relationship(lazy="joined")


class MovementAllocation(Base):
    """Exact stock levels affected by a movement (signed quantity)."""

    __tablename__ = "movement_allocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    movement_id: Mapped[str] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    pallet_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pallets.id", ondelete="SET NULL"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)

    movement: Mapped[StockMovement] = relationship(back_populates="allocations")
    location: Mapped[Location] = relationship(lazy="joined")
    pallet: Mapped[Optional[Pallet]] = relationship(lazy="joined")


# ---------------------------------------------------------------------------
# Invoices and documents
# ---------------------------------------------------------------------------
class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    supplier_id: Mapped[Optional[str]] = mapped_column(ForeignKey("suppliers.id"), index=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        enum_column(InvoiceStatus, "invoice_status"), default=InvoiceStatus.RECEIVED, nullable=False
    )
    source: Mapped[InvoiceSource] = mapped_column(
        enum_column(InvoiceSource, "invoice_source"), default=InvoiceSource.UPLOAD, nullable=False
    )
    ocr_status: Mapped[OCRStatus] = mapped_column(
        enum_column(OCRStatus, "ocr_status"), default=OCRStatus.NOT_CONFIGURED, nullable=False
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    original_filename: Mapped[Optional[str]] = mapped_column(String(255))
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    uploaded_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    supplier: Mapped[Optional[Supplier]] = relationship(lazy="joined")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (UniqueConstraint("supplier_id", "number", name="uq_invoice_supplier_number"),)


class InvoiceLine(Base, TimestampMixin):
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[Optional[str]] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_ref: Mapped[Optional[str]] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("21"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"), nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
    product: Mapped[Optional[Product]] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("invoice_id", "line_number", name="uq_invoice_line_number"),
        CheckConstraint("quantity > 0", name="invoice_line_quantity_positive"),
    )


# ---------------------------------------------------------------------------
# Audit trail (append-only; enforced by DB triggers as well)
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    actor_label: Mapped[str] = mapped_column(String(150), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    before: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    after: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# Phase 7/8 foundation tables
# ---------------------------------------------------------------------------
class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"), index=True)
    event_type: Mapped[AttendanceEventType] = mapped_column(
        enum_column(AttendanceEventType, "attendance_event_type"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    device_label: Mapped[Optional[str]] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    employee: Mapped[Employee] = relationship(lazy="joined")


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plate: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    capacity_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Delivery(Base, TimestampMixin):
    __tablename__ = "deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    vehicle_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vehicles.id"))
    driver_employee_id: Mapped[Optional[str]] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[DeliveryStatus] = mapped_column(
        enum_column(DeliveryStatus, "delivery_status"), default=DeliveryStatus.DRAFT, nullable=False
    )
    destination_name: Mapped[str] = mapped_column(String(150), nullable=False)
    destination_address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    planned_departure: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    departed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus, "task_status"), default=TaskStatus.PENDING, nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    assigned_to: Mapped[Optional[str]] = mapped_column(ForeignKey("employees.id"))
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    assigned_employee: Mapped[Optional["Employee"]] = relationship(
        foreign_keys=[assigned_to], lazy="joined"
    )
    creator: Mapped[Optional["User"]] = relationship(foreign_keys=[created_by], lazy="joined")

    __table_args__ = (CheckConstraint("priority BETWEEN 1 AND 5", name="task_priority_range"),)


class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    incident_type: Mapped[IncidentType] = mapped_column(
        enum_column(IncidentType, "incident_type"),
        default=IncidentType.OTHER,
        server_default="OTHER",
        nullable=False,
    )
    severity: Mapped[IncidentSeverity] = mapped_column(
        enum_column(IncidentSeverity, "incident_severity"),
        default=IncidentSeverity.LOW,
        nullable=False,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        enum_column(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN, nullable=False
    )
    reported_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_to: Mapped[Optional[str]] = mapped_column(ForeignKey("employees.id"))
    location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"))
    product_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    pallet_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("pallets.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str] = mapped_column(Text, default="", nullable=False)

    reporter: Mapped[Optional["User"]] = relationship(foreign_keys=[reported_by], lazy="joined")
    assignee: Mapped[Optional["Employee"]] = relationship(foreign_keys=[assigned_to], lazy="joined")
    location: Mapped[Optional["Location"]] = relationship(foreign_keys=[location_id], lazy="joined")
    product: Mapped[Optional["Product"]] = relationship(foreign_keys=[product_id], lazy="joined")
    pallet: Mapped[Optional["Pallet"]] = relationship(foreign_keys=[pallet_id], lazy="joined")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="info", nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AISession(Base):
    __tablename__ = "ai_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    transcript: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)


class AIAction(Base):
    """Every AI proposal. Actions are never executed without human approval."""

    __tablename__ = "ai_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ai_session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("ai_sessions.id", ondelete="SET NULL"))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="proposed", nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CallRecord(Base):
    __tablename__ = "call_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    incident_id: Mapped[Optional[str]] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(60))
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    authorized_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
