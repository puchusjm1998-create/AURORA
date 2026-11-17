export type Decimal = string | number;

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

export type RoleLevel = 1 | 2 | 3 | 4 | 5;

export interface EmployeeBrief {
  id: string;
  code: string;
  first_name: string;
  last_name: string;
  department: string;
  position: string;
}

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  role_level: RoleLevel;
  role_code: string;
  role_name: string;
  permissions: string[];
  must_change_password: boolean;
  employee: EmployeeBrief | null;
}

export interface Role {
  id: number;
  code: string;
  name: string;
  level: RoleLevel;
  description: string;
}

export interface UserAccount {
  id: string;
  email: string;
  full_name: string;
  role_id: number;
  role_level: RoleLevel;
  role_name: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
  employee: EmployeeBrief | null;
}

export interface Employee {
  id: string;
  code: string;
  first_name: string;
  last_name: string;
  department: string;
  position: string;
  status: "active" | "leave" | "inactive";
  hire_date: string | null;
  phone: string | null;
  user_id: string | null;
  created_at: string;
}

export interface Warehouse {
  id: string;
  code: string;
  name: string;
  address: string;
  city: string;
  postal_code: string;
  country: string;
  timezone: string;
  is_active: boolean;
  created_at: string;
  location_count: number;
}

export interface Location {
  id: string;
  warehouse_id: string | null;
  warehouse_code: string | null;
  full_code: string;
  aisle: string;
  rack: string;
  level: string;
  position: string;
  label: string;
  capacity_pallets: number;
  capacity_units: Decimal | null;
  is_pick_face: boolean;
  is_active: boolean;
  occupied_pallets: number;
  occupied_units: Decimal;
}

export interface Supplier {
  id: string;
  name: string;
  tax_id: string | null;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  is_active: boolean;
}

export type TrackingMode = "quantity" | "batch" | "unit";

export interface StockSummary {
  on_hand: Decimal;
  reserved: Decimal;
  available: Decimal;
  in_transit: Decimal;
  locations: number;
  unit_count: number;
  value: Decimal;
}

export interface Product {
  id: string;
  sku: string;
  name: string;
  description: string;
  category: string;
  manufacturer_ref: string | null;
  barcode: string | null;
  supplier_id: string | null;
  supplier: { id: string; name: string } | null;
  uom: string;
  purchase_price: Decimal;
  unit_price: Decimal;
  min_stock: Decimal;
  tracking_mode: TrackingMode;
  is_active: boolean;
  created_at: string;
  stock: StockSummary;
}

export interface StockLevel {
  id: string;
  product_id: string;
  product_sku: string;
  product_name: string;
  uom: string;
  location_id: string;
  quantity: Decimal;
  reserved_quantity: Decimal;
  available_quantity: Decimal;
  location_code: string;
  location_label: string;
  warehouse_code: string;
  warehouse_name: string;
  pallet_id: string | null;
  pallet_code: string | null;
  aisle: string;
  rack: string;
  level: string;
  position: string;
  updated_at: string;
}

export interface ProductWhereabouts {
  product: Product;
  stock: StockSummary;
  positions: StockLevel[];
}

export interface ProductUnit {
  id: string;
  code: string;
  product_id: string;
  serial_number: string | null;
  batch_code: string | null;
  status: "in_stock" | "reserved" | "shipped" | "damaged" | "returned";
  pallet_code: string | null;
  location_code: string | null;
  created_at: string;
}

export type PalletStatus = "open" | "sealed" | "in_transit" | "shipped" | "empty";

export interface PalletItem {
  id: string;
  product_id: string;
  quantity: Decimal;
  batch_code: string | null;
  product: Product;
}

export interface Pallet {
  id: string;
  code: string;
  status: PalletStatus;
  warehouse_id: string;
  warehouse_code: string;
  location_id: string | null;
  location_code: string | null;
  invoice_id: string | null;
  notes: string;
  gross_weight_kg: Decimal | null;
  item_count: number;
  total_units: Decimal;
  sealed_at: string | null;
  created_at: string;
  items: PalletItem[];
}

export type MovementType =
  | "reception"
  | "shipment"
  | "internal_move"
  | "relocation"
  | "picking"
  | "replenishment"
  | "putaway"
  | "return"
  | "adjustment"
  | "load"
  | "unload";

export type MovementStatus = "draft" | "confirmed" | "cancelled";

export interface MovementAllocation {
  location_code: string;
  pallet_code: string | null;
  quantity: Decimal;
}

export interface Movement {
  id: string;
  reference: string;
  movement_type: MovementType;
  status: MovementStatus;
  product_id: string;
  product_sku: string;
  product_name: string;
  uom: string;
  quantity: Decimal;
  batch_code: string | null;
  from_location_id: string | null;
  from_location_code: string | null;
  to_location_id: string | null;
  to_location_code: string | null;
  from_pallet_id: string | null;
  from_pallet_code: string | null;
  to_pallet_id: string | null;
  to_pallet_code: string | null;
  worker_id: string | null;
  worker_name: string | null;
  reason: string;
  document_ref: string;
  invoice_id: string | null;
  physical_confirmed: boolean;
  confirmed_at: string | null;
  created_at: string;
  created_by: string | null;
  created_by_name: string | null;
  allocations: MovementAllocation[];
  unit_codes: string[];
}

export interface Reservation {
  id: string;
  reference: string;
  product_id: string;
  product_sku: string;
  product_name: string;
  location_id: string;
  location_code: string;
  pallet_id: string | null;
  quantity: Decimal;
  status: "active" | "released" | "consumed" | "expired";
  created_at: string;
  expires_at: string | null;
}

export type TaskStatus = "pending" | "in_progress" | "blocked" | "done" | "cancelled";

export interface Task {
  id: string;
  code: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: number;
  assigned_to: string | null;
  assignee_name: string | null;
  assignee_code: string | null;
  created_by_name: string;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface InvoiceLine {
  id: string;
  line_number: number;
  product_id: string | null;
  supplier_ref: string | null;
  description: string;
  quantity: Decimal;
  unit_price: Decimal;
  discount_pct: Decimal;
  tax_rate: Decimal;
  line_total: Decimal;
  received_quantity: Decimal;
  review_required: boolean;
  product_sku: string | null;
  product_name: string | null;
}

export interface Invoice {
  id: string;
  number: string;
  supplier_id: string | null;
  supplier_name: string | null;
  invoice_date: string;
  due_date: string | null;
  subtotal: Decimal;
  tax_total: Decimal;
  total: Decimal;
  currency: string;
  status: "received" | "in_review" | "reconciled" | "discrepancy";
  ocr_status: string;
  original_filename: string | null;
  mime_type: string | null;
  file_path: string | null;
  file_sha256: string | null;
  notes: string;
  created_at: string;
  reconciled_at: string | null;
  lines: InvoiceLine[];
}

export type AttendanceEventType = "clock_in" | "clock_out" | "break_start" | "break_end";

export interface AttendanceRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  employee_code: string;
  event_type: AttendanceEventType;
  occurred_at: string;
  recorded_at: string;
  source: string;
  device_label: string | null;
  note: string;
}

export interface AttendanceMe {
  employee: EmployeeBrief;
  date: string;
  state: "out" | "in" | "break";
  since: string | null;
  worked_minutes: number;
  break_minutes: number;
  today: AttendanceRecord[];
  week_minutes: number;
}

export interface AttendanceSummaryRow {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  days: number;
  worked_minutes: number;
  break_minutes: number;
  first_in: string | null;
  last_out: string | null;
}

export interface AttendanceSummary {
  date_from: string;
  date_to: string;
  total_worked_minutes: number;
  items: AttendanceSummaryRow[];
}

export interface PutawayCandidate {
  location_id: string;
  location_code: string;
  is_pick_face: boolean;
  capacity_pallets: number;
  occupied_pallets: number;
  free_pallets: number;
  units: Decimal;
  same_product_units: Decimal;
  distance_m: number;
  score: number;
  reasons: string[];
}

export interface PutawaySuggestion {
  product_id: string;
  product_sku: string;
  product_name: string;
  pallets: number;
  fast_mover: boolean;
  moves: number;
  fits: boolean;
  candidates: PutawayCandidate[];
  assumptions: Record<string, number>;
  note: string;
}

export interface RouteStop {
  sequence: number;
  location_id: string;
  location_code: string;
  product_id: string | null;
  product_sku: string | null;
  product_name: string | null;
  quantity: Decimal | null;
  pallet_code: string | null;
  distance_from_previous_m: number;
  pick_seconds: number;
}

export interface PickingRoute {
  stops: RouteStop[];
  total_distance_m: number;
  total_pick_seconds: number;
  return_to_dispatch: boolean;
  assumptions: Record<string, number>;
  note: string;
}

export interface SlottingRow {
  product_id: string;
  product_sku: string;
  product_name: string;
  moves: number;
  units_out: Decimal;
  locations: number;
  in_pick_face: boolean;
  nearest_distance_m: number | null;
  on_hand: Decimal;
  recommendation: string;
  reason: string;
}

export interface SlottingReport {
  days: number;
  items: SlottingRow[];
  total: number;
  assumptions: Record<string, number>;
  note: string;
}

export type IncidentType = "damage" | "discrepancy" | "quality" | "safety" | "other";
export type IncidentStatus = "open" | "acknowledged" | "resolved" | "closed";
export type IncidentSeverity = "low" | "medium" | "high" | "critical";

export interface Incident {
  id: string;
  code: string;
  title: string;
  description: string;
  incident_type: IncidentType;
  severity: IncidentSeverity;
  status: IncidentStatus;
  location_id: string | null;
  location_code: string | null;
  product_id: string | null;
  product_sku: string | null;
  product_name: string | null;
  pallet_id: string | null;
  pallet_code: string | null;
  reported_by_name: string | null;
  assigned_to: string | null;
  assignee_name: string | null;
  assignee_code: string | null;
  resolution: string;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DashboardKpis {
  products: number;
  active_products: number;
  locations: number;
  occupancy_pct: number;
  pallets_stored: number;
  pallets_open: number;
  total_units: Decimal;
  stock_value: Decimal;
  movements_today: number;
  receptions_today: number;
  shipments_today: number;
  movements_draft: number;
  low_stock_products: number;
  pending_invoices: number;
  workers_active: number;
  open_tasks: number;
  overdue_tasks: number;
  active_reservations: number;
  reserved_units: Decimal;
  open_incidents: number;
  critical_incidents: number;
}

export interface DashboardData {
  kpis: DashboardKpis;
  warehouse_occupancy: {
    warehouse_code: string;
    warehouse_name: string;
    locations: number;
    occupied: number;
    capacity_pallets: number;
  }[];
  top_products: { sku: string; name: string; quantity: string; value: string }[];
  low_stock: { sku: string; name: string; min_stock: string; on_hand: string }[];
  recent_activity: {
    id: string;
    reference: string;
    type: MovementType;
    type_label: string;
    status: MovementStatus;
    product: string;
    quantity: string;
    uom: string;
    from_location: string | null;
    to_location: string | null;
    created_at: string;
  }[];
}

export interface AuditEntry {
  id: string;
  actor_label: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
}

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  demo_mode: boolean;
  server_time_utc: string;
  warehouse_timezone: string;
  phase: string;
  implemented: string[];
  pending: string[];
}

export interface ScanResult {
  kind: "product" | "pallet" | "unit" | "location" | "employee";
  code: string;
  title: string;
  subtitle: string;
  target_type: string;
  target_id: string | null;
  href: string;
  extra: Record<string, unknown>;
}

export interface LabelData {
  payload: string;
  kind: string;
  title: string;
  code: string;
  lines: string[];
}

export interface WarehouseLayout {
  warehouse: { id: string; code: string; name: string };
  aisles: {
    aisle: string;
    racks: {
      rack: string;
      locations: Location[];
    }[];
  }[];
}

export interface ValuationSummary {
  generated_at: string;
  currency: string;
  categories: {
    category: string;
    products: number;
    units: string;
    purchase_value: string;
    sale_value: string;
  }[];
}
