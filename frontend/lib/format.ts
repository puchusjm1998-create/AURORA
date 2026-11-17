import type { MovementStatus, MovementType, PalletStatus, TrackingMode } from "./types";

const MADRID = "Europe/Madrid";

export const num = (value: string | number | null | undefined): number => {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export function fmtQty(value: string | number | null | undefined, uom?: string): string {
  const numeric = num(value);
  const formatted = new Intl.NumberFormat("es-ES", {
    maximumFractionDigits: 3,
    minimumFractionDigits: 0,
  }).format(numeric);
  return uom ? `${formatted} ${uom}` : formatted;
}

export function fmtMoney(value: string | number | null | undefined, currency = "EUR"): string {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(num(value));
}

export function fmtNumber(value: string | number | null | undefined, digits = 0): string {
  return new Intl.NumberFormat("es-ES", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(num(value));
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-");
    return `${d}/${m}/${y}`;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: MADRID,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: MADRID,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: MADRID,
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function fmtRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.round(diffMs / 60000);
  if (Math.abs(minutes) < 1) return "ahora";
  if (Math.abs(minutes) < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return `hace ${hours} h`;
  return fmtDateTime(value);
}

export function todayMadrid(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: MADRID }).format(new Date());
}

export const MOVEMENT_TYPES: { value: MovementType; label: string }[] = [
  { value: "reception", label: "Recepción" },
  { value: "shipment", label: "Expedición" },
  { value: "internal_move", label: "Movimiento interno" },
  { value: "relocation", label: "Reubicación" },
  { value: "picking", label: "Preparación de pedidos" },
  { value: "replenishment", label: "Reposición" },
  { value: "putaway", label: "Estocaje" },
  { value: "return", label: "Devolución" },
  { value: "adjustment", label: "Ajuste autorizado" },
  { value: "load", label: "Carga" },
  { value: "unload", label: "Descarga" },
];

const MOVEMENT_LABELS: Record<string, string> = Object.fromEntries(
  MOVEMENT_TYPES.map((item) => [item.value, item.label]),
);

export const movementLabel = (value: string): string => MOVEMENT_LABELS[value] ?? value;

export const DIRECTION_LABELS: Record<string, string> = {
  reception: "Entrada",
  return: "Entrada",
  unload: "Entrada",
  shipment: "Salida",
  picking: "Salida",
  load: "Salida",
  internal_move: "Transferencia",
  relocation: "Transferencia",
  replenishment: "Transferencia",
  putaway: "Transferencia",
  adjustment: "Ajuste",
};

export const movementDirection = (value: string): "in" | "out" | "move" => {
  if (["reception", "return", "unload"].includes(value)) return "in";
  if (["shipment", "picking", "load"].includes(value)) return "out";
  return "move";
};

export const movementBadge: Record<MovementStatus, { tone: string; label: string }> = {
  confirmed: { tone: "success", label: "Confirmado" },
  draft: { tone: "warning", label: "Borrador" },
  cancelled: { tone: "danger", label: "Cancelado" },
};

export const palletStatusMeta: Record<PalletStatus, { tone: string; label: string }> = {
  open: { tone: "warning", label: "Abierto" },
  sealed: { tone: "success", label: "Precintado" },
  in_transit: { tone: "info", label: "En tránsito" },
  shipped: { tone: "neutral", label: "Expedido" },
  empty: { tone: "neutral", label: "Vacío" },
};

export const invoiceStatusMeta: Record<string, { tone: string; label: string }> = {
  received: { tone: "info", label: "Recibida" },
  in_review: { tone: "warning", label: "En revisión" },
  reconciled: { tone: "success", label: "Conciliada" },
  discrepancy: { tone: "danger", label: "Discrepancia" },
};

export const taskStatusMeta: Record<string, { tone: string; label: string }> = {
  pending: { tone: "warning", label: "Pendiente" },
  in_progress: { tone: "info", label: "En curso" },
  blocked: { tone: "danger", label: "Bloqueada" },
  done: { tone: "success", label: "Completada" },
  cancelled: { tone: "neutral", label: "Cancelada" },
};

export const taskPriorityMeta: Record<number, { tone: string; label: string }> = {
  1: { tone: "danger", label: "Crítica" },
  2: { tone: "warning", label: "Alta" },
  3: { tone: "info", label: "Media" },
  4: { tone: "neutral", label: "Baja" },
  5: { tone: "neutral", label: "Mínima" },
};

export const reservationStatusMeta: Record<string, { tone: string; label: string }> = {
  active: { tone: "success", label: "Activa" },
  released: { tone: "neutral", label: "Liberada" },
  consumed: { tone: "info", label: "Consumida" },
  expired: { tone: "warning", label: "Caducada" },
};

export const trackingLabel: Record<TrackingMode, string> = {
  quantity: "Cantidad",
  batch: "Lote",
  unit: "Unidad individual",
};

export const employeeStatusMeta: Record<string, { tone: string; label: string }> = {
  active: { tone: "success", label: "Activo" },
  leave: { tone: "warning", label: "Baja temporal" },
  inactive: { tone: "neutral", label: "Inactivo" },
};

export const unitStatusMeta: Record<string, { tone: string; label: string }> = {
  in_stock: { tone: "success", label: "En stock" },
  reserved: { tone: "info", label: "Reservada" },
  shipped: { tone: "neutral", label: "Expedida" },
  damaged: { tone: "danger", label: "Dañada" },
  returned: { tone: "warning", label: "Devuelta" },
};

export const roleLevelLabel: Record<number, string> = {
  1: "Nivel 1 · Administrador",
  2: "Nivel 2 · Logística",
  3: "Nivel 3 · Encargado",
  4: "Nivel 4 · Trabajador",
  5: "Nivel 5 · Auditor",
};

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "AU";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function occupancyTone(percent: number): string {
  if (percent >= 95) return "danger";
  if (percent >= 75) return "warning";
  return "success";
}

export function makeIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `key-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function truncate(value: string, max = 48): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

export function warehouseTimeNow(): string {
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: MADRID,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());
}
