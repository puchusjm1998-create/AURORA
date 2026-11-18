"use client";

import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { fmtDate } from "@/lib/format";
import type {
  Employee,
  Page,
  ShiftAssignment,
  ShiftPlan,
  ShiftPlanRow,
  Warehouse,
  WorkShift,
} from "@/lib/types";
import {
  Badge,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  Stat,
  useToast,
} from "@/components/ui";
import {
  IconCheck,
  IconChevron,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconUsers,
} from "@/components/icons";

const WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

function isoDate(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(
    value.getDate(),
  ).padStart(2, "0")}`;
}

function parseIso(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function addDays(value: Date, days: number): Date {
  const copy = new Date(value);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function mondayOf(value: Date): Date {
  const copy = new Date(value);
  const offset = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - offset);
  return copy;
}

function shortTime(value: string): string {
  return value.slice(0, 5);
}

interface ShiftForm {
  warehouse_id: string;
  name: string;
  start_time: string;
  end_time: string;
  days_of_week: number[];
  required_headcount: number;
}

const INITIAL_SHIFT: ShiftForm = {
  warehouse_id: "",
  name: "",
  start_time: "06:00",
  end_time: "14:00",
  days_of_week: [0, 1, 2, 3, 4],
  required_headcount: 1,
};

export default function ShiftsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const canManage = can("workers.write");
  const [weekStart, setWeekStart] = useState("");
  const [shiftOpen, setShiftOpen] = useState(false);
  const [shiftForm, setShiftForm] = useState<ShiftForm>(INITIAL_SHIFT);
  const [saving, setSaving] = useState(false);
  const [assignTarget, setAssignTarget] = useState<{ shift: ShiftPlanRow; date: string } | null>(null);
  const [assignForm, setAssignForm] = useState({ employee_id: "", note: "" });
  const [toDelete, setToDelete] = useState<WorkShift | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    setWeekStart(isoDate(mondayOf(new Date())));
  }, []);

  const weekEnd = weekStart ? isoDate(addDays(parseIso(weekStart), 6)) : "";
  const plan = useApi<ShiftPlan>(
    weekStart ? `/api/v1/shifts/plan?date_from=${weekStart}&date_to=${weekEnd}` : null,
    [weekStart],
  );
  const shifts = useApi<WorkShift[]>("/api/v1/shifts");
  const employees = useApi<Page<Employee>>(can("workers.read") ? "/api/v1/employees?limit=200" : null);
  const warehouses = useApi<Page<Warehouse>>(can("locations.read") ? "/api/v1/warehouses" : null);

  const totals = useMemo(() => {
    let required = 0;
    let assigned = 0;
    (plan.data?.days ?? []).forEach((day) => {
      day.shifts.forEach((row) => {
        required += row.required_headcount;
        assigned += row.assigned_count;
      });
    });
    return { required, assigned };
  }, [plan.data]);

  function reload() {
    plan.reload();
    shifts.reload();
  }

  async function createShift() {
    if (!shiftForm.warehouse_id || shiftForm.name.trim().length < 2) {
      toast.error("Faltan datos", "Indique almacén y nombre del turno.");
      return;
    }
    if (shiftForm.days_of_week.length === 0) {
      toast.error("Faltan días", "Seleccione al menos un día de la semana.");
      return;
    }
    setSaving(true);
    try {
      await api<WorkShift>("/api/v1/shifts", {
        method: "POST",
        body: {
          ...shiftForm,
          name: shiftForm.name.trim(),
          start_time: `${shiftForm.start_time}:00`,
          end_time: `${shiftForm.end_time}:00`,
        },
      });
      toast.success("Turno creado", "Ya aparece en el plan semanal.");
      setShiftOpen(false);
      setShiftForm({ ...INITIAL_SHIFT, warehouse_id: shiftForm.warehouse_id });
      reload();
    } catch (err) {
      toast.error("No se pudo crear", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function assign() {
    if (!assignTarget) return;
    if (!assignForm.employee_id) {
      toast.error("Falta la persona", "Seleccione un empleado activo.");
      return;
    }
    setSaving(true);
    try {
      await api<ShiftAssignment>(
        `/api/v1/shifts/${assignTarget.shift.shift_id}/assignments`,
        {
          method: "POST",
          body: {
            employee_id: assignForm.employee_id,
            work_date: assignTarget.date,
            note: assignForm.note,
          },
        },
      );
      toast.success("Turno asignado", "La cobertura se actualiza al instante.");
      setAssignTarget(null);
      setAssignForm({ employee_id: "", note: "" });
      plan.reload();
    } catch (err) {
      toast.error("No se pudo asignar", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function unassign(assignment: ShiftAssignment) {
    setBusy(assignment.id);
    try {
      await api(`/api/v1/shifts/${assignment.shift_id}/assignments/${assignment.id}`, {
        method: "DELETE",
      });
      toast.success("Asignación retirada");
      plan.reload();
    } catch (err) {
      toast.error("No se pudo retirar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function toggleShift(shift: WorkShift) {
    setBusy(shift.id);
    try {
      await api<WorkShift>(`/api/v1/shifts/${shift.id}`, {
        method: "PATCH",
        body: { is_active: !shift.is_active },
      });
      toast.success(shift.is_active ? "Turno pausado" : "Turno activo");
      reload();
    } catch (err) {
      toast.error("No se pudo actualizar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function deleteShift() {
    if (!toDelete) return;
    setBusy(toDelete.id);
    try {
      await api(`/api/v1/shifts/${toDelete.id}`, { method: "DELETE" });
      toast.success("Turno eliminado");
      setToDelete(null);
      reload();
    } catch (err) {
      toast.error("No se pudo eliminar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (!can("workers.read")) {
    return (
      <>
        <PageHeader eyebrow="Equipo" title="Turnos" />
        <div className="alert warning">
          <strong>Acceso restringido</strong>
          <span>Su perfil no dispone de permiso para consultar la planificación de turnos.</span>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Equipo"
        title="Turnos de trabajo"
        subtitle="Planificación semanal por almacén con cobertura exigida y control de solapes."
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setWeekStart(isoDate(addDays(parseIso(weekStart), -7)))}
              aria-label="Semana anterior"
            >
              <IconChevron style={{ transform: "rotate(180deg)" }} />
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setWeekStart(isoDate(mondayOf(new Date())))}
            >
              Esta semana
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setWeekStart(isoDate(addDays(parseIso(weekStart), 7)))}
              aria-label="Semana siguiente"
            >
              <IconChevron />
            </button>
            <button type="button" className="btn btn-ghost" onClick={reload}>
              <IconRefresh /> Actualizar
            </button>
            {canManage ? (
              <button type="button" className="btn btn-primary" onClick={() => setShiftOpen(true)}>
                <IconPlus /> Nuevo turno
              </button>
            ) : null}
          </>
        }
      />

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Stat
          label="Semana"
          value={weekStart ? `${fmtDate(weekStart)}` : "—"}
          meta={<span>hasta {weekEnd ? fmtDate(weekEnd) : "—"}</span>}
        />
        <Stat label="Turnos planificados" value={plan.data?.days.reduce((acc, day) => acc + day.shifts.length, 0) ?? 0} />
        <Stat
          label="Cobertura"
          value={`${totals.assigned}/${totals.required}`}
          meta={<span>personas asignadas / necesarias</span>}
          accent={totals.assigned >= totals.required}
        />
        <Stat
          label="Huecos"
          value={plan.data?.uncovered_shifts ?? 0}
          meta={<span>turnos por debajo de cobertura</span>}
        />
      </div>

      {plan.error ? <ErrorBlock message={plan.error} onRetry={plan.reload} /> : null}
      {plan.loading && !plan.data ? <LoadingBlock label="Cargando plan semanal…" /> : null}

      {plan.data ? (
        <div className="stack" style={{ gap: 14, marginBottom: 18 }}>
          {plan.data.days.map((day) => (
            <Card
              key={day.work_date}
              title={`${WEEKDAYS[day.weekday]} · ${fmtDate(day.work_date)}`}
              subtitle={day.shifts.length ? `${day.shifts.length} turno(s)` : "Sin turnos planificados"}
              actions={
                day.shifts.some((row) => row.missing > 0) ? (
                  <Badge tone="warning">
                    {day.shifts.reduce((acc, row) => acc + row.missing, 0)} hueco(s)
                  </Badge>
                ) : day.shifts.length ? (
                  <Badge tone="success">Cobertura completa</Badge>
                ) : null
              }
            >
              {day.shifts.length === 0 ? (
                <p className="small text-muted">No hay turnos activos que incluyan este día.</p>
              ) : (
                <div className="stack" style={{ gap: 12 }}>
                  {day.shifts.map((row) => (
                    <div key={`${row.shift_id}-${day.work_date}`} className="shift-row">
                      <div className="shift-head">
                        <div>
                          <strong>{row.name}</strong>
                          <span className="small text-muted" style={{ marginLeft: 8 }}>
                            {shortTime(row.start_time)}–{shortTime(row.end_time)}
                          </span>
                        </div>
                        <div className="row" style={{ gap: 6 }}>
                          <Badge tone={row.missing ? "warning" : "success"}>
                            {row.assigned_count}/{row.required_headcount}
                          </Badge>
                          {canManage ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => {
                                setAssignTarget({ shift: row, date: day.work_date });
                                setAssignForm({ employee_id: "", note: "" });
                              }}
                            >
                              <IconUsers /> Asignar
                            </button>
                          ) : null}
                        </div>
                      </div>
                      {row.assigned.length ? (
                        <div className="row" style={{ gap: 6 }}>
                          {row.assigned.map((assignment) => (
                            <span key={assignment.id} className="chip">
                              {assignment.employee_name}
                              {canManage ? (
                                <button
                                  type="button"
                                  onClick={() => unassign(assignment)}
                                  disabled={busy === assignment.id}
                                  aria-label={`Quitar a ${assignment.employee_name}`}
                                  className="chip-remove"
                                >
                                  ×
                                </button>
                              ) : null}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="tiny text-muted">Sin personas asignadas.</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      ) : null}

      <Card
        title="Plantillas de turno"
        subtitle="Los cambios de horario o días afectan a las semanas futuras"
        flush
      >
        {shifts.error ? <ErrorBlock message={shifts.error} onRetry={shifts.reload} /> : null}
        {shifts.data && shifts.data.length === 0 ? (
          <EmptyState
            icon={<IconUsers />}
            title="Sin turnos configurados"
            description="Cree una plantilla con horario, días y cobertura mínima."
            action={
              canManage ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setShiftOpen(true)}>
                  Nuevo turno
                </button>
              ) : undefined
            }
          />
        ) : null}
        {shifts.data && shifts.data.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Turno</th>
                  <th>Almacén</th>
                  <th>Horario</th>
                  <th>Días</th>
                  <th className="num">Cobertura</th>
                  <th>Estado</th>
                  {canManage ? <th /> : null}
                </tr>
              </thead>
              <tbody>
                {shifts.data.map((shift) => (
                  <tr key={shift.id}>
                    <td className="strong">{shift.name}</td>
                    <td className="small">{shift.warehouse_code ?? "—"}</td>
                    <td className="mono small">
                      {shortTime(shift.start_time)}–{shortTime(shift.end_time)}
                    </td>
                    <td className="small">
                      {shift.days_of_week.map((day) => WEEKDAYS[day].slice(0, 3)).join(", ")}
                    </td>
                    <td className="num">{shift.required_headcount}</td>
                    <td>
                      <Badge tone={shift.is_active ? "success" : "neutral"}>
                        {shift.is_active ? "Activo" : "Pausado"}
                      </Badge>
                    </td>
                    {canManage ? (
                      <td className="actions">
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => toggleShift(shift)}
                          disabled={busy === shift.id}
                        >
                          {shift.is_active ? "Pausar" : "Activar"}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => setToDelete(shift)}
                          disabled={busy === shift.id}
                          aria-label={`Eliminar ${shift.name}`}
                        >
                          <IconTrash />
                        </button>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <Modal
        open={shiftOpen}
        title="Nuevo turno"
        subtitle="Plantilla semanal; después asigne personas día a día"
        onClose={() => setShiftOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setShiftOpen(false)}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" onClick={createShift} disabled={saving}>
              {saving ? <span className="spinner" /> : <IconPlus />} Crear turno
            </button>
          </>
        }
      >
        <div className="form-grid">
          <Field label="Almacén" required>
            <select
              className="select"
              value={shiftForm.warehouse_id}
              onChange={(event) => setShiftForm({ ...shiftForm, warehouse_id: event.target.value })}
            >
              <option value="">Seleccione…</option>
              {(warehouses.data?.items ?? []).map((warehouse) => (
                <option key={warehouse.id} value={warehouse.id}>
                  {warehouse.code} · {warehouse.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Nombre" required>
            <input
              className="input"
              value={shiftForm.name}
              maxLength={80}
              onChange={(event) => setShiftForm({ ...shiftForm, name: event.target.value })}
              placeholder="Mañana"
            />
          </Field>
          <Field label="Inicio" required>
            <input
              className="input"
              type="time"
              value={shiftForm.start_time}
              onChange={(event) => setShiftForm({ ...shiftForm, start_time: event.target.value })}
            />
          </Field>
          <Field label="Fin" required>
            <input
              className="input"
              type="time"
              value={shiftForm.end_time}
              onChange={(event) => setShiftForm({ ...shiftForm, end_time: event.target.value })}
            />
          </Field>
          <Field label="Personas necesarias" required>
            <input
              className="input"
              type="number"
              min={1}
              max={200}
              value={shiftForm.required_headcount}
              onChange={(event) =>
                setShiftForm({ ...shiftForm, required_headcount: Number(event.target.value) })
              }
            />
          </Field>
          <Field label="Días" className="full" required>
            <div className="row" style={{ gap: 10 }}>
              {WEEKDAYS.map((label, index) => (
                <label key={label} className="tiny" style={{ display: "flex", gap: 5, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={shiftForm.days_of_week.includes(index)}
                    onChange={(event) =>
                      setShiftForm({
                        ...shiftForm,
                        days_of_week: event.target.checked
                          ? [...shiftForm.days_of_week, index].sort()
                          : shiftForm.days_of_week.filter((day) => day !== index),
                      })
                    }
                  />
                  {label.slice(0, 3)}
                </label>
              ))}
            </div>
          </Field>
        </div>
      </Modal>

      <Modal
        open={assignTarget !== null}
        title={`Asignar a ${assignTarget?.shift.name ?? "turno"}`}
        subtitle={
          assignTarget
            ? `${fmtDate(assignTarget.date)} · ${shortTime(assignTarget.shift.start_time)}–${shortTime(
                assignTarget.shift.end_time,
              )}`
            : undefined
        }
        onClose={() => setAssignTarget(null)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setAssignTarget(null)}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" onClick={assign} disabled={saving}>
              {saving ? <span className="spinner" /> : <IconCheck />} Asignar
            </button>
          </>
        }
      >
        <div className="form-grid">
          <Field label="Persona" className="full" required>
            <select
              className="select"
              value={assignForm.employee_id}
              onChange={(event) => setAssignForm({ ...assignForm, employee_id: event.target.value })}
            >
              <option value="">Seleccione…</option>
              {(employees.data?.items ?? [])
                .filter((employee) => employee.status === "active")
                .map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.first_name} {employee.last_name} · {employee.code}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Nota" className="full" hint="Opcional: refuerzo, cambio de turno…">
            <input
              className="input"
              value={assignForm.note}
              maxLength={255}
              onChange={(event) => setAssignForm({ ...assignForm, note: event.target.value })}
            />
          </Field>
        </div>
        {assignTarget ? (
          <p className="small text-muted" style={{ marginTop: 10 }}>
            Cobertura actual: {assignTarget.shift.assigned_count}/{assignTarget.shift.required_headcount}.
            No se permiten dos turnos solapados para la misma persona.
          </p>
        ) : null}
      </Modal>

      <ConfirmDialog
        open={toDelete !== null}
        title="Eliminar turno"
        message={
          <>
            Se eliminará la plantilla <strong>{toDelete?.name}</strong>. Si tiene asignaciones, el sistema
            pedirá pausarla para conservar el historial.
          </>
        }
        confirmLabel="Eliminar"
        danger
        busy={busy === toDelete?.id}
        onConfirm={deleteShift}
        onClose={() => setToDelete(null)}
      />
    </>
  );
}
