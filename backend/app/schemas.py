"""Pydantic schemas for the public API.

Datetime values are always normalised to UTC on the way out (ISO-8601 with a
``Z`` suffix); the frontend renders them in Europe/Madrid.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.core.enums import (
    AttendanceEventType,
    DeliveryStatus,
    EmployeeStatus,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    InvoiceStatus,
    MovementStatus,
    MovementType,
    PalletStatus,
    ReservationStatus,
    TaskStatus,
    TrackingMode,
    UnitStatus,
)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    from datetime import timezone

    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime, PlainSerializer(_utc_iso, return_type=Optional[str], when_used="json")
]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class ORMBase(APIModel):
    id: str


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Message(BaseModel):
    message: str
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Auth & users
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RoleRead(ORMBase):
    id: int
    code: str
    name: str
    level: int
    description: str


class EmployeeBrief(ORMBase):
    code: str
    first_name: str
    last_name: str
    department: str
    position: str

    @property
    def full_name(self) -> str:  # pragma: no cover - convenience
        return f"{self.first_name} {self.last_name}"


class UserMe(BaseModel):
    id: str
    email: str
    full_name: str
    role_level: int
    role_code: str
    role_name: str
    permissions: list[str]
    must_change_password: bool
    employee: Optional[EmployeeBrief] = None


class UserRead(ORMBase):
    email: str
    full_name: str
    role_id: int
    role_level: int
    role_name: str
    is_active: bool
    must_change_password: bool
    last_login_at: Optional[UtcDateTime] = None
    created_at: UtcDateTime
    employee: Optional[EmployeeBrief] = None


class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str
    role_level: int = Field(ge=1, le=5)
    employee_id: Optional[str] = None
    must_change_password: bool = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role_level: Optional[int] = Field(default=None, ge=1, le=5)
    is_active: Optional[bool] = None
    employee_id: Optional[str] = None


class PasswordResetRequest(BaseModel):
    new_password: str
    must_change_password: bool = True


# ---------------------------------------------------------------------------
# Personnel
# ---------------------------------------------------------------------------
class EmployeeCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=120)
    department: str = ""
    position: str = ""
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    hire_date: Optional[date] = None
    phone: Optional[str] = None


class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    status: Optional[EmployeeStatus] = None
    hire_date: Optional[date] = None
    phone: Optional[str] = None


class EmployeeRead(ORMBase):
    code: str
    first_name: str
    last_name: str
    department: str
    position: str
    status: EmployeeStatus
    hire_date: Optional[date] = None
    phone: Optional[str] = None
    user_id: Optional[str] = None
    created_at: UtcDateTime


# ---------------------------------------------------------------------------
# Warehouse structure
# ---------------------------------------------------------------------------
class WarehouseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9\-]+$")
    name: str = Field(min_length=1, max_length=120)
    address: str = ""
    city: str = ""
    postal_code: str = ""
    country: str = Field(default="ES", min_length=2, max_length=2)
    timezone: str = "Europe/Madrid"


class WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None


class WarehouseRead(ORMBase):
    code: str
    name: str
    address: str
    city: str
    postal_code: str
    country: str
    timezone: str
    is_active: bool
    created_at: UtcDateTime
    location_count: int = 0


class LocationCreate(BaseModel):
    warehouse_id: str
    aisle: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9\-]+$")
    rack: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9\-]+$")
    level: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9\-]+$")
    position: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9\-]+$")
    label: str = ""
    capacity_pallets: int = Field(default=1, ge=0, le=1000)
    capacity_units: Optional[Decimal] = Field(default=None, ge=0)
    is_pick_face: bool = False


class LocationUpdate(BaseModel):
    label: Optional[str] = None
    capacity_pallets: Optional[int] = Field(default=None, ge=0, le=1000)
    capacity_units: Optional[Decimal] = Field(default=None, ge=0)
    is_pick_face: Optional[bool] = None
    is_active: Optional[bool] = None


class LocationRead(ORMBase):
    warehouse_id: Optional[str] = None
    warehouse_code: Optional[str] = None
    full_code: str
    aisle: str
    rack: str
    level: str
    position: str
    label: str
    capacity_pallets: int
    capacity_units: Optional[Decimal] = None
    is_pick_face: bool
    is_active: bool
    occupied_pallets: int = 0
    occupied_units: Decimal = Decimal("0")


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    tax_id: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    tax_id: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierRead(ORMBase):
    name: str
    tax_id: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    is_active: bool


class SupplierBrief(ORMBase):
    name: str


# ---------------------------------------------------------------------------
# Products & stock
# ---------------------------------------------------------------------------
class ProductCreate(BaseModel):
    sku: Optional[str] = Field(default=None, max_length=40)
    name: str = Field(min_length=1, max_length=180)
    description: str = ""
    category: str = "General"
    manufacturer_ref: Optional[str] = None
    barcode: Optional[str] = None
    supplier_id: Optional[str] = None
    uom: str = Field(default="ud", max_length=16)
    purchase_price: Decimal = Field(default=Decimal("0"), ge=0)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    min_stock: Decimal = Field(default=Decimal("0"), ge=0)
    tracking_mode: TrackingMode = TrackingMode.QUANTITY


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    manufacturer_ref: Optional[str] = None
    barcode: Optional[str] = None
    supplier_id: Optional[str] = None
    uom: Optional[str] = None
    purchase_price: Optional[Decimal] = Field(default=None, ge=0)
    unit_price: Optional[Decimal] = Field(default=None, ge=0)
    min_stock: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class StockSummary(BaseModel):
    on_hand: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")
    available: Decimal = Decimal("0")
    in_transit: Decimal = Decimal("0")
    locations: int = 0
    unit_count: int = 0
    value: Decimal = Decimal("0")


class ProductRead(ORMBase):
    sku: str
    name: str
    description: str
    category: str
    manufacturer_ref: Optional[str] = None
    barcode: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier: Optional[SupplierBrief] = None
    uom: str
    purchase_price: Decimal
    unit_price: Decimal
    min_stock: Decimal
    tracking_mode: TrackingMode
    is_active: bool
    created_at: UtcDateTime
    stock: StockSummary = StockSummary()


class StockLevelRead(BaseModel):
    id: str
    product_id: str
    product_sku: str
    product_name: str
    uom: str
    location_id: str
    quantity: Decimal
    reserved_quantity: Decimal
    available_quantity: Decimal
    location_code: str
    location_label: str
    warehouse_code: str
    warehouse_name: str
    pallet_id: Optional[str] = None
    pallet_code: Optional[str] = None
    aisle: str
    rack: str
    level: str
    position: str
    updated_at: UtcDateTime


class ProductLocationRead(BaseModel):
    location_code: str
    warehouse_code: str
    pallet_code: Optional[str] = None
    quantity: Decimal
    reserved_quantity: Decimal
    available_quantity: Decimal


class ProductWhereabouts(BaseModel):
    product: ProductRead
    stock: StockSummary
    positions: list[StockLevelRead]


class UnitRead(ORMBase):
    code: str
    product_id: str
    serial_number: Optional[str] = None
    batch_code: Optional[str] = None
    status: UnitStatus
    pallet_code: Optional[str] = None
    location_code: Optional[str] = None
    created_at: UtcDateTime


# ---------------------------------------------------------------------------
# Pallets
# ---------------------------------------------------------------------------
class PalletCreate(BaseModel):
    warehouse_id: str
    location_id: Optional[str] = None
    notes: str = ""
    gross_weight_kg: Optional[Decimal] = Field(default=None, ge=0)
    invoice_id: Optional[str] = None


class PalletUpdate(BaseModel):
    notes: Optional[str] = None
    gross_weight_kg: Optional[Decimal] = Field(default=None, ge=0)


class PalletItemRead(ORMBase):
    product_id: str
    quantity: Decimal
    batch_code: Optional[str] = None
    product: ProductRead


class PalletAddItem(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0)
    batch_code: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_line_id: Optional[str] = None
    unit_serials: list[str] | None = None


class PalletRead(ORMBase):
    code: str
    status: PalletStatus
    warehouse_id: str
    warehouse_code: str
    location_id: Optional[str] = None
    location_code: Optional[str] = None
    invoice_id: Optional[str] = None
    notes: str
    gross_weight_kg: Optional[Decimal] = None
    item_count: int = 0
    total_units: Decimal = Decimal("0")
    sealed_at: Optional[UtcDateTime] = None
    created_at: UtcDateTime
    items: list[PalletItemRead] = []


class PalletMove(BaseModel):
    destination_location_id: str
    worker_id: Optional[str] = None
    reason: str = "Reubicación de palé"


class PalletShip(BaseModel):
    worker_id: Optional[str] = None
    document_ref: str = ""
    reason: str = "Expedición de palé"


# ---------------------------------------------------------------------------
# Movements
# ---------------------------------------------------------------------------
class MovementCreate(BaseModel):
    movement_type: MovementType
    product_id: str
    quantity: Decimal
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    from_pallet_id: Optional[str] = None
    to_pallet_id: Optional[str] = None
    worker_id: Optional[str] = None
    batch_code: Optional[str] = None
    reason: str = ""
    document_ref: str = ""
    invoice_id: Optional[str] = None
    invoice_line_id: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=80)
    unit_serials: Optional[list[str]] = None
    unit_codes: Optional[list[str]] = None
    reservation_id: Optional[str] = None
    confirm: bool = True
    physical_confirmed: bool = False


class MovementConfirm(BaseModel):
    physical_confirmed: bool = True
    reservation_id: Optional[str] = None


class MovementCancel(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class MovementAllocationRead(BaseModel):
    location_code: str
    pallet_code: Optional[str] = None
    quantity: Decimal


class MovementRead(ORMBase):
    reference: str
    movement_type: MovementType
    status: MovementStatus
    product_id: str
    product_sku: str
    product_name: str
    uom: str
    quantity: Decimal
    batch_code: Optional[str] = None
    from_location_id: Optional[str] = None
    from_location_code: Optional[str] = None
    to_location_id: Optional[str] = None
    to_location_code: Optional[str] = None
    from_pallet_id: Optional[str] = None
    from_pallet_code: Optional[str] = None
    to_pallet_id: Optional[str] = None
    to_pallet_code: Optional[str] = None
    worker_id: Optional[str] = None
    worker_name: Optional[str] = None
    reason: str
    document_ref: str
    invoice_id: Optional[str] = None
    physical_confirmed: bool
    confirmed_at: Optional[UtcDateTime] = None
    created_at: UtcDateTime
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    allocations: list[MovementAllocationRead] = []
    unit_codes: list[str] = []


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    priority: int = Field(default=3, ge=1, le=5)
    assigned_to: Optional[str] = None
    due_at: Optional[datetime] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    assigned_to: Optional[str] = None
    due_at: Optional[datetime] = None


class TaskRead(ORMBase):
    code: str
    title: str
    description: str
    status: TaskStatus
    priority: int
    assigned_to: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_code: Optional[str] = None
    created_by_name: str = ""
    due_at: Optional[UtcDateTime] = None
    completed_at: Optional[UtcDateTime] = None
    created_at: UtcDateTime


class VehicleCreate(BaseModel):
    plate: str = Field(min_length=2, max_length=16)
    model: str = ""
    capacity_kg: Optional[Decimal] = None
    is_active: bool = True


class VehicleUpdate(BaseModel):
    plate: Optional[str] = Field(default=None, min_length=2, max_length=16)
    model: Optional[str] = None
    capacity_kg: Optional[Decimal] = None
    is_active: Optional[bool] = None


class VehicleRead(ORMBase):
    plate: str
    model: str
    capacity_kg: Optional[Decimal] = None
    is_active: bool
    created_at: UtcDateTime


class DeliveryCreate(BaseModel):
    destination_name: str = Field(min_length=1, max_length=150)
    destination_address: str = ""
    vehicle_id: Optional[str] = None
    driver_employee_id: Optional[str] = None
    planned_departure: Optional[datetime] = None
    notes: str = ""


class DeliveryUpdate(BaseModel):
    destination_name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    destination_address: Optional[str] = None
    vehicle_id: Optional[str] = None
    driver_employee_id: Optional[str] = None
    planned_departure: Optional[datetime] = None
    notes: Optional[str] = None


class DeliveryPalletAdd(BaseModel):
    pallet_id: str


class DeliveryFail(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DeliveryItemRead(BaseModel):
    product_id: str
    product_sku: str
    product_name: str
    quantity: Decimal
    batch_code: Optional[str] = None


class DeliveryPalletRead(BaseModel):
    pallet_id: str
    pallet_code: str
    status: PalletStatus
    location_code: Optional[str] = None
    total_units: Decimal
    items: list[DeliveryItemRead]


class DeliveryRead(ORMBase):
    reference: str
    status: DeliveryStatus
    destination_name: str
    destination_address: str
    vehicle_id: Optional[str] = None
    vehicle_plate: Optional[str] = None
    driver_employee_id: Optional[str] = None
    driver_name: Optional[str] = None
    planned_departure: Optional[UtcDateTime] = None
    departed_at: Optional[UtcDateTime] = None
    delivered_at: Optional[UtcDateTime] = None
    notes: str = ""
    pallets: list[DeliveryPalletRead]
    total_units: Decimal
    created_at: UtcDateTime
    updated_at: UtcDateTime


class AttendanceCreate(BaseModel):
    employee_id: Optional[str] = None
    event_type: AttendanceEventType
    occurred_at: Optional[datetime] = None
    note: str = ""
    device_label: Optional[str] = None


class AttendanceRead(ORMBase):
    employee_id: str
    employee_name: str
    employee_code: str
    event_type: AttendanceEventType
    occurred_at: UtcDateTime
    recorded_at: UtcDateTime
    source: str
    device_label: Optional[str] = None
    note: str = ""


class AttendanceMe(BaseModel):
    employee: EmployeeBrief
    date: date
    state: Literal["out", "in", "break"]
    since: Optional[UtcDateTime] = None
    worked_minutes: int
    break_minutes: int
    today: list[AttendanceRead]
    week_minutes: int


class AttendanceSummaryRow(BaseModel):
    employee_id: str
    employee_code: str
    employee_name: str
    days: int
    worked_minutes: int
    break_minutes: int
    first_in: Optional[UtcDateTime] = None
    last_out: Optional[UtcDateTime] = None


class AttendanceSummary(BaseModel):
    date_from: date
    date_to: date
    total_worked_minutes: int
    items: list[AttendanceSummaryRow]


class PutawayCandidate(BaseModel):
    location_id: str
    location_code: str
    is_pick_face: bool
    capacity_pallets: int
    occupied_pallets: int
    free_pallets: int
    units: Decimal
    same_product_units: Decimal
    distance_m: float
    score: float
    reasons: list[str]


class PutawaySuggestion(BaseModel):
    product_id: str
    product_sku: str
    product_name: str
    pallets: int
    fast_mover: bool
    moves: int
    fits: bool
    candidates: list[PutawayCandidate]
    assumptions: dict[str, float]
    note: str


class RouteRequest(BaseModel):
    reservation_reference: Optional[str] = None
    location_ids: list[str] = Field(default_factory=list, max_length=50)
    return_to_dispatch: bool = True


class RouteStop(BaseModel):
    sequence: int
    location_id: str
    location_code: str
    product_id: Optional[str] = None
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[Decimal] = None
    pallet_code: Optional[str] = None
    distance_from_previous_m: float
    pick_seconds: int


class PickingRoute(BaseModel):
    stops: list[RouteStop]
    total_distance_m: float
    total_pick_seconds: int
    return_to_dispatch: bool
    assumptions: dict[str, float]
    note: str


class SlottingRow(BaseModel):
    product_id: str
    product_sku: str
    product_name: str
    moves: int
    units_out: Decimal
    locations: int
    in_pick_face: bool
    nearest_distance_m: Optional[float] = None
    on_hand: Decimal
    recommendation: str
    reason: str


class SlottingReport(BaseModel):
    days: int
    items: list[SlottingRow]
    total: int
    assumptions: dict[str, float]
    note: str


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    incident_type: IncidentType = IncidentType.OTHER
    severity: IncidentSeverity = IncidentSeverity.LOW
    location_id: Optional[str] = None
    product_id: Optional[str] = None
    pallet_id: Optional[str] = None
    assigned_to: Optional[str] = None


class IncidentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = None
    incident_type: Optional[IncidentType] = None
    severity: Optional[IncidentSeverity] = None
    location_id: Optional[str] = None
    product_id: Optional[str] = None
    pallet_id: Optional[str] = None
    assigned_to: Optional[str] = None


class IncidentResolve(BaseModel):
    resolution: str = Field(min_length=5, max_length=4000)


class IncidentRead(ORMBase):
    code: str
    title: str
    description: str
    incident_type: IncidentType
    severity: IncidentSeverity
    status: IncidentStatus
    location_id: Optional[str] = None
    location_code: Optional[str] = None
    product_id: Optional[str] = None
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    pallet_id: Optional[str] = None
    pallet_code: Optional[str] = None
    reported_by_name: Optional[str] = None
    assigned_to: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_code: Optional[str] = None
    resolution: str = ""
    resolved_at: Optional[UtcDateTime] = None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ReservationCreate(BaseModel):
    product_id: str
    location_id: str
    pallet_id: Optional[str] = None
    quantity: Decimal = Field(gt=0)
    reference: str = Field(min_length=1, max_length=60)
    expires_at: Optional[datetime] = None


class ReservationRead(ORMBase):
    reference: str
    product_id: str
    product_sku: str
    product_name: str
    location_id: str
    location_code: str
    pallet_id: Optional[str] = None
    quantity: Decimal
    status: ReservationStatus
    created_at: UtcDateTime
    expires_at: Optional[UtcDateTime] = None


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
class InvoiceLineCreate(BaseModel):
    supplier_ref: Optional[str] = None
    description: str = ""
    product_id: Optional[str] = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    tax_rate: Decimal = Field(default=Decimal("21"), ge=0, le=100)


class InvoiceLineRead(ORMBase):
    line_number: int
    product_id: Optional[str] = None
    supplier_ref: Optional[str] = None
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    tax_rate: Decimal
    line_total: Decimal
    received_quantity: Decimal
    review_required: bool
    product_sku: Optional[str] = None
    product_name: Optional[str] = None


class InvoiceRead(ORMBase):
    number: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    invoice_date: date
    due_date: Optional[date] = None
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    currency: str
    status: InvoiceStatus
    ocr_status: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_path: Optional[str] = None
    file_sha256: Optional[str] = None
    notes: str
    created_at: UtcDateTime
    reconciled_at: Optional[UtcDateTime] = None
    lines: list[InvoiceLineRead] = []


class InvoiceUpdate(BaseModel):
    number: Optional[str] = None
    supplier_id: Optional[str] = None
    invoice_date: Optional[date] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Audit, dashboard, system
# ---------------------------------------------------------------------------
class AuditRead(ORMBase):
    actor_label: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    created_at: UtcDateTime


class DashboardKpis(BaseModel):
    products: int
    active_products: int
    locations: int
    occupancy_pct: float
    pallets_stored: int
    pallets_open: int
    total_units: Decimal
    stock_value: Decimal
    movements_today: int
    receptions_today: int
    shipments_today: int
    movements_draft: int
    low_stock_products: int
    pending_invoices: int
    workers_active: int
    open_tasks: int
    overdue_tasks: int
    active_reservations: int
    reserved_units: Decimal
    open_incidents: int
    critical_incidents: int


class DashboardActivity(BaseModel):
    reference: str
    movement_type: MovementType
    product_name: str
    quantity: Decimal
    from_location_code: Optional[str] = None
    to_location_code: Optional[str] = None
    status: MovementStatus
    created_at: UtcDateTime
    actor: Optional[str] = None


class WarehouseOccupancy(BaseModel):
    warehouse_code: str
    warehouse_name: str
    locations: int
    occupied: int
    capacity_pallets: int


class DashboardRead(BaseModel):
    kpis: DashboardKpis
    warehouse_occupancy: list[WarehouseOccupancy]
    top_products: list[dict[str, Any]]
    low_stock: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]


class SystemInfo(BaseModel):
    name: str
    version: str
    environment: str
    demo_mode: bool
    server_time_utc: str
    warehouse_timezone: str
    phase: str
    implemented: list[str]
    pending: list[str]


class ScanResult(BaseModel):
    kind: str
    code: str
    title: str
    subtitle: str = ""
    target_type: str
    target_id: Optional[str] = None
    href: str
    extra: dict[str, Any] = {}
