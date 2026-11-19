"""Domain enumerations shared by models, services and API schemas."""

from __future__ import annotations

from enum import StrEnum


class RoleLevel(int):
    """Documentation helper; persisted as an integer 1..5."""


class PermissionCode(StrEnum):
    # Inventory & warehousing
    INVENTORY_READ = "inventory.read"
    INVENTORY_WRITE = "inventory.write"
    INVENTORY_DELETE = "inventory.delete"
    LOCATIONS_READ = "locations.read"
    LOCATIONS_WRITE = "locations.write"
    PALLETS_READ = "pallets.read"
    PALLETS_WRITE = "pallets.write"
    MOVEMENTS_READ = "movements.read"
    MOVEMENTS_WRITE = "movements.write"
    MOVEMENTS_CONFIRM = "movements.confirm"
    MOVEMENTS_CANCEL = "movements.cancel"
    RESERVATIONS_READ = "reservations.read"
    RESERVATIONS_WRITE = "reservations.write"
    # Documents
    INVOICES_READ = "invoices.read"
    INVOICES_WRITE = "invoices.write"
    INVOICES_RECONCILE = "invoices.reconcile"
    # Tasks
    TASKS_READ = "tasks.read"
    TASKS_WRITE = "tasks.write"
    TASKS_COMPLETE = "tasks.complete"
    # People
    WORKERS_READ = "workers.read"
    WORKERS_WRITE = "workers.write"
    ATTENDANCE_READ = "attendance.read"
    ATTENDANCE_MANAGE = "attendance.manage"
    ATTENDANCE_CLOCK = "attendance.clock"
    # Transport & incidents
    DELIVERIES_READ = "deliveries.read"
    DELIVERIES_WRITE = "deliveries.write"
    DELIVERIES_TRACK = "deliveries.track"
    INCIDENTS_READ = "incidents.read"
    INCIDENTS_WRITE = "incidents.write"
    INCIDENTS_REPORT = "incidents.report"
    # Reporting & governance
    REPORTS_READ = "reports.read"
    REPORTS_EXPORT = "reports.export"
    AUDIT_READ = "audit.read"
    USERS_MANAGE = "users.manage"
    ROLES_MANAGE = "roles.manage"
    SETTINGS_MANAGE = "settings.manage"
    # AURORA assistant (Phase 5) – human approval is still required for actions
    AI_USE = "ai.use"
    AI_APPROVE_ACTIONS = "ai.approve_actions"
    CALLS_MANAGE = "calls.manage"


class TrackingMode(StrEnum):
    QUANTITY = "quantity"  # bulk / unit of measure only
    BATCH = "batch"  # lot tracking (batch code)
    UNIT = "unit"  # one code per physical item (AUR-OBJ-*)


class PalletStatus(StrEnum):
    OPEN = "open"  # being built
    SEALED = "sealed"  # closed, stored
    IN_TRANSIT = "in_transit"
    SHIPPED = "shipped"
    EMPTY = "empty"


class MovementType(StrEnum):
    RECEPTION = "reception"
    SHIPMENT = "shipment"
    INTERNAL_MOVE = "internal_move"
    RELOCATION = "relocation"
    PICKING = "picking"
    REPLENISHMENT = "replenishment"
    PUTAWAY = "putaway"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    LOAD = "load"
    UNLOAD = "unload"


class MovementStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class MovementDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"


INBOUND_TYPES = {MovementType.RECEPTION, MovementType.RETURN, MovementType.UNLOAD}
OUTBOUND_TYPES = {MovementType.SHIPMENT, MovementType.PICKING, MovementType.LOAD}
TRANSFER_TYPES = {
    MovementType.INTERNAL_MOVE,
    MovementType.RELOCATION,
    MovementType.REPLENISHMENT,
    MovementType.PUTAWAY,
}


def movement_direction(movement_type: MovementType) -> MovementDirection:
    if movement_type in INBOUND_TYPES:
        return MovementDirection.INBOUND
    if movement_type in OUTBOUND_TYPES:
        return MovementDirection.OUTBOUND
    if movement_type == MovementType.ADJUSTMENT:
        return MovementDirection.ADJUSTMENT
    return MovementDirection.TRANSFER


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class UnitStatus(StrEnum):
    IN_STOCK = "in_stock"
    RESERVED = "reserved"
    SHIPPED = "shipped"
    DAMAGED = "damaged"
    RETURNED = "returned"


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    LEAVE = "leave"
    INACTIVE = "inactive"


class InvoiceStatus(StrEnum):
    RECEIVED = "received"  # uploaded, pending review
    IN_REVIEW = "in_review"
    RECONCILED = "reconciled"
    DISCREPANCY = "discrepancy"


class InvoiceSource(StrEnum):
    UPLOAD = "upload"
    MANUAL = "manual"


class OCRStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class DeliveryStatus(StrEnum):
    DRAFT = "draft"
    PREPARING = "preparing"
    READY = "ready"
    LOADED = "loaded"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class IncidentSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentType(StrEnum):
    DAMAGE = "damage"
    DISCREPANCY = "discrepancy"
    QUALITY = "quality"
    SAFETY = "safety"
    OTHER = "other"


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class AttendanceEventType(StrEnum):
    CLOCK_IN = "clock_in"
    CLOCK_OUT = "clock_out"
    BREAK_START = "break_start"
    BREAK_END = "break_end"


ROLE_DEFINITIONS: dict[int, tuple[str, str]] = {
    1: ("Administrador principal", "Acceso completo, configuración, autorizaciones críticas"),
    2: ("Responsable de logística", "Inventario, movimientos, planificación y operaciones"),
    3: ("Encargado", "Supervisión, recepción, expedición y validación de tareas"),
    4: ("Trabajador", "Consulta de tareas, escaneo QR y confirmación de operaciones"),
    5: ("Auditor", "Consulta autorizada e historial de auditoría"),
}

class ReportKind(StrEnum):
    INVENTORY = "inventory"
    MOVEMENTS = "movements"


class ReportFormat(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"
    CSV = "csv"


class ScheduleFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduleRunStatus(StrEnum):
    SENT = "sent"
    FAILED = "failed"

class AlertMetric(StrEnum):
    OPEN_TASKS = "open_tasks"
    OVERDUE_TASKS = "overdue_tasks"
    OPEN_INCIDENTS = "open_incidents"
    ACTIVE_RESERVATIONS = "active_reservations"
    PENDING_DELIVERIES = "pending_deliveries"
    LOW_STOCK_PRODUCTS = "low_stock_products"
    STOCK_UNITS = "stock_units"


class AlertOperator(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class CalibrationMethod(StrEnum):
    MANUAL = "manual"
    REGRESSION = "regression"


class NfcCardStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class NfcTapAction(StrEnum):
    AUTO = "auto"
    CLOCK_IN = "clock_in"
    CLOCK_OUT = "clock_out"
    BREAK_START = "break_start"
    BREAK_END = "break_end"



class CallStatus(StrEnum):
    HANDOFF = "handoff"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
