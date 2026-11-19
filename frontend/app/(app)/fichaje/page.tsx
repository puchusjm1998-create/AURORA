"use client";

import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import {
  attendanceEventMeta,
  attendanceStateMeta,
  fmtDate,
  fmtMinutes,
  fmtSignedMinutes,
  fmtTime,
  todayMadrid,
} from "@/lib/format";
import type {
  AttendanceEventType,
  AttendanceMe,
  AttendanceRecord,
  AttendanceSummary,
  Employee,
  HoursBankSummary,
  Page,
} from "@/lib/types";
import {
  Badge,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  Stat,
  useToast,
} from "@/components/ui";
import { IconClock, IconPlus, IconRefresh } from "@/components/icons";

function shiftDate(iso: string, days: number): string {
  const date = new Date(`${iso}T12:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

const BUTTONS: { event: AttendanceEventType; label: string; className: string; from: string[] }[] = [
  { event: "clock_in", label: "Fichar entrada", className: "btn-primary", from: ["out"] },
  { event: "break_start", label: "Iniciar pausa", className: "btn-ghost", from: ["in"] },
  { event: "break_end", label: "Finalizar pausa", className: "btn-ghost", from: ["break"] },
  { event: "clock_out", label: "Fichar salida", className: "btn-danger", from: ["in", "break"] },
];

export default function AttendancePage() {
  const { can } = useAuth();
  const toast = useToast();
  const canRead = can("attendance.read");
  const canManage = can("attendance.manage");

  const me = useApi<AttendanceMe>("/api/v1/attendance/me");
  const bank = useApi<HoursBankSummary>("/api/v1/hours-bank/me");
  const [busy, setBusy] = useState(false);

  const [today, setToday] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  useEffect(() => {
    const current = todayMadrid();
    setToday(current);
    setFrom(shiftDate(current, -6));
    setTo(current);
  }, []);

  const employees = useApi<Page<Employee>>(
    canRead ? "/api/v1/employees?status=active&limit=200" : null,
  );
  const summary = useApi<AttendanceSummary>(
    canRead && from && to
      ? withQuery("/api/v1/attendance/summary", { date_from: from, date_to: to })
      : null,
    [from, to, canRead],
  );
  const records = useApi<Page<AttendanceRecord>>(
    canRead && from && to
      ? withQuery("/api/v1/attendance", {
          employee_id: employeeId || null,
          date_from: from,
          date_to: to,
          limit: 100,
        })
      : null,
    [employeeId, from, to, canRead],
  );

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    employee_id: "",
    event_type: "clock_in" as AttendanceEventType,
    occurred_at: "",
    note: "",
  });
  const [error, setError] = useState<string | null>(null);

  const meta = me.data ? attendanceStateMeta[me.data.state] : null;
  const availableButtons = useMemo(
    () => BUTTONS.filter((button) => me.data && button.from.includes(me.data.state)),
    [me.data],
  );

  async function punch(event: AttendanceEventType) {
    setBusy(true);
    try {
      await api("/api/v1/attendance", { method: "POST", body: { event_type: event } });
      toast.success("Fichaje registrado", attendanceEventMeta[event]?.label ?? event);
      me.reload();
      bank.reload();
      summary.reload();
      records.reload();
    } catch (err) {
      toast.error("No se pudo fichar", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function openManual() {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
    setForm({ employee_id: "", event_type: "clock_in", occurred_at: local, note: "" });
    setError(null);
    setOpen(true);
  }

  async function createManual(event: React.FormEvent) {
    event.preventDefault();
    if (!form.employee_id) {
      setError("Seleccione el trabajador.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/attendance", {
        method: "POST",
        body: {
          employee_id: form.employee_id,
          event_type: form.event_type,
          occurred_at: form.occurred_at ? new Date(form.occurred_at).toISOString() : null,
          note: form.note.trim(),
        },
      });
      toast.success("Fichaje manual registrado", "Queda auditado con su usuario.");
      setOpen(false);
      summary.reload();
      records.reload();
      me.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Equipo"
        title="Fichaje y jornada"
        subtitle="Entrada, salida y pausas con registro inmutable. El estado que ve se calcula siempre en el servidor a partir de los fichajes."
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                me.reload();
                summary.reload();
                records.reload();
              }}
              disabled={busy}
            >
              <IconRefresh /> Actualizar
            </button>
            {canManage ? (
              <button type="button" className="btn btn-primary" onClick={openManual}>
                <IconPlus /> Registro manual
              </button>
            ) : null}
          </>
        }
      />

      {me.error ? (
        <div className="alert warning" style={{ marginBottom: 16 }}>
          <strong>No se puede mostrar su jornada</strong>
          <span>{me.error}</span>
        </div>
      ) : null}

      {me.data ? (
        <>
          <section className="card" style={{ marginBottom: 18 }}>
            <div className="card-body">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <div className="eyebrow">Mi jornada</div>
                  <div className="strong" style={{ fontSize: 17 }}>
                    {me.data.employee.first_name} {me.data.employee.last_name}
                  </div>
                  <div className="tiny text-muted">
                    {me.data.employee.code} · {me.data.employee.position || me.data.employee.department}
                  </div>
                </div>
                <Badge tone={(meta?.tone ?? "neutral") as "success"}>
                  {meta?.label ?? me.data.state}
                </Badge>
              </div>

              <div className="grid grid-3" style={{ marginTop: 16 }}>
                <Stat
                  label="Trabajado hoy"
                  value={fmtMinutes(me.data.worked_minutes)}
                  meta={
                    <span>
                      {me.data.state === "in" && me.data.since
                        ? `desde las ${fmtTime(me.data.since)}`
                        : "jornada cerrada o sin empezar"}
                    </span>
                  }
                  accent
                />
                <Stat
                  label="Pausas hoy"
                  value={fmtMinutes(me.data.break_minutes)}
                  meta={<span>{me.data.state === "break" ? "en pausa ahora" : "tiempo no trabajado"}</span>}
                />
                <Stat
                  label="Esta semana"
                  value={fmtMinutes(me.data.week_minutes)}
                  meta={<span>desde el lunes</span>}
                />
              </div>

              {bank.data && bank.data.items.length > 0 ? (
                <div className="row" style={{ marginTop: 12, alignItems: "baseline" }}>
                  <span className="small text-muted">Bolsa de horas del mes:</span>
                  <strong
                    style={{
                      color:
                        bank.data.items[0].balance_minutes >= 0
                          ? "var(--success, #15803d)"
                          : "var(--danger, #b91c1c)",
                    }}
                  >
                    {fmtSignedMinutes(bank.data.items[0].balance_minutes)}
                  </strong>
                  <span className="tiny text-muted">
                    {fmtMinutes(bank.data.items[0].worked_minutes)} fichadas ·{" "}
                    {fmtMinutes(bank.data.items[0].contracted_minutes)} teóricas · ajustes{" "}
                    {fmtSignedMinutes(bank.data.items[0].adjustments_minutes)}
                  </span>
                </div>
              ) : null}

              <div className="row" style={{ marginTop: 16 }}>
                {availableButtons.length === 0 ? (
                  <span className="small text-muted">No hay acciones disponibles.</span>
                ) : null}
                {availableButtons.map((button) => (
                  <button
                    key={button.event}
                    type="button"
                    className={`btn ${button.className}`}
                    disabled={busy}
                    onClick={() => punch(button.event)}
                  >
                    {busy ? <span className="spinner" /> : <IconClock />} {button.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Hora</th>
                    <th>Fichaje</th>
                    <th>Origen</th>
                    <th>Nota</th>
                  </tr>
                </thead>
                <tbody>
                  {me.data.today.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="small text-muted">
                        Todavía no hay fichajes hoy ({fmtDate(me.data.date)}).
                      </td>
                    </tr>
                  ) : null}
                  {me.data.today.map((record) => {
                    const event = attendanceEventMeta[record.event_type] ?? {
                      tone: "neutral",
                      label: record.event_type,
                    };
                    return (
                      <tr key={record.id}>
                        <td className="mono nowrap">{fmtTime(record.occurred_at)}</td>
                        <td>
                          <Badge tone={event.tone as "success"}>{event.label}</Badge>
                        </td>
                        <td className="small text-muted">
                          {record.source === "manual"
                            ? "Manual (responsable)"
                            : record.source === "nfc"
                              ? "Tarjeta NFC"
                              : "Web"}
                        </td>
                        <td className="small text-muted">{record.note || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {canRead ? (
            <>
              <section className="card" style={{ marginBottom: 18 }}>
                <div className="toolbar">
                  <strong className="small">Horas por trabajador</strong>
                  <span className="spacer" />
                  <input
                    className="input"
                    type="date"
                    value={from}
                    max={to || today}
                    onChange={(event) => setFrom(event.target.value)}
                    aria-label="Desde"
                  />
                  <input
                    className="input"
                    type="date"
                    value={to}
                    min={from}
                    max={today}
                    onChange={(event) => setTo(event.target.value)}
                    aria-label="Hasta"
                  />
                  <span className="count-chip">
                    {summary.data ? fmtMinutes(summary.data.total_worked_minutes) : "—"}
                  </span>
                </div>
                {summary.error ? (
                  <div style={{ padding: 16 }}>
                    <ErrorBlock message={summary.error} onRetry={summary.reload} />
                  </div>
                ) : null}
                {summary.loading && !summary.data ? (
                  <LoadingBlock label="Calculando horas…" />
                ) : null}
                {summary.data && summary.data.items.length === 0 ? (
                  <EmptyState
                    icon={<IconClock />}
                    title="Sin fichajes en el periodo"
                    description="No hay registros de entrada o salida para estas fechas."
                  />
                ) : null}
                {summary.data && summary.data.items.length > 0 ? (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Trabajador</th>
                          <th className="num">Días</th>
                          <th className="num">Trabajado</th>
                          <th className="num">Pausas</th>
                          <th>Primera entrada</th>
                          <th>Última salida</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.data.items.map((row) => (
                          <tr key={row.employee_id}>
                            <td>
                              <div className="strong small">{row.employee_name}</div>
                              <div className="tiny mono text-muted">{row.employee_code}</div>
                            </td>
                            <td className="num">{row.days}</td>
                            <td className="num strong">{fmtMinutes(row.worked_minutes)}</td>
                            <td className="num">{fmtMinutes(row.break_minutes)}</td>
                            <td className="small nowrap">
                              {row.first_in ? `${fmtDate(row.first_in)} ${fmtTime(row.first_in)}` : "—"}
                            </td>
                            <td className="small nowrap">
                              {row.last_out ? `${fmtDate(row.last_out)} ${fmtTime(row.last_out)}` : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </section>

              <section className="card">
                <div className="toolbar">
                  <strong className="small">Últimos fichajes</strong>
                  <select
                    className="select"
                    value={employeeId}
                    onChange={(event) => setEmployeeId(event.target.value)}
                    aria-label="Trabajador"
                  >
                    <option value="">Todo el equipo</option>
                    {employees.data?.items.map((employee) => (
                      <option key={employee.id} value={employee.id}>
                        {employee.first_name} {employee.last_name}
                      </option>
                    ))}
                  </select>
                  <span className="spacer" />
                  <span className="count-chip">
                    {records.data ? `${records.data.total} registros` : "—"}
                  </span>
                </div>
                {records.error ? (
                  <div style={{ padding: 16 }}>
                    <ErrorBlock message={records.error} onRetry={records.reload} />
                  </div>
                ) : null}
                {records.loading && !records.data ? <LoadingBlock label="Cargando fichajes…" /> : null}
                {records.data && records.data.items.length === 0 ? (
                  <EmptyState
                    icon={<IconClock />}
                    title="Sin registros"
                    description="No hay fichajes para el filtro seleccionado."
                  />
                ) : null}
                {records.data && records.data.items.length > 0 ? (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Fecha y hora</th>
                          <th>Trabajador</th>
                          <th>Fichaje</th>
                          <th>Origen</th>
                          <th>Nota</th>
                        </tr>
                      </thead>
                      <tbody>
                        {records.data.items.map((record) => {
                          const event = attendanceEventMeta[record.event_type] ?? {
                            tone: "neutral",
                            label: record.event_type,
                          };
                          return (
                            <tr key={record.id}>
                              <td className="small nowrap">
                                {fmtDate(record.occurred_at)} · {fmtTime(record.occurred_at)}
                              </td>
                              <td>
                                <div className="small strong">{record.employee_name}</div>
                                <div className="tiny mono text-muted">{record.employee_code}</div>
                              </td>
                              <td>
                                <Badge tone={event.tone as "success"}>{event.label}</Badge>
                              </td>
                              <td className="small text-muted">
                                {record.source === "manual" ? "Manual" : "Web"}
                              </td>
                              <td className="small text-muted">{record.note || "—"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </section>
            </>
          ) : null}
        </>
      ) : null}

      {!me.data && me.loading ? <LoadingBlock label="Cargando su jornada…" /> : null}

      <div className="alert" style={{ marginTop: 14 }}>
        <strong>Fichajes inmutables</strong>
        <span>
          No se pueden editar ni borrar: una corrección es un fichaje nuevo y queda en auditoría con
          el usuario que lo registró. La planificación de turnos todavía no está implementada.
        </span>
      </div>

      <Modal
        open={open}
        title="Registro manual de fichaje"
        subtitle="Para olvidos de tarjeta o correcciones acordadas con el trabajador"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="attendance-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Registrar
            </button>
          </>
        }
      >
        <form id="attendance-form" className="stack" onSubmit={createManual}>
          <div className="form-grid">
            <Field label="Trabajador" required>
              <select
                className="select"
                value={form.employee_id}
                onChange={(event) => setForm({ ...form, employee_id: event.target.value })}
                required
              >
                <option value="">Seleccione…</option>
                {employees.data?.items.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.first_name} {employee.last_name} · {employee.code}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Fichaje" required>
              <select
                className="select"
                value={form.event_type}
                onChange={(event) =>
                  setForm({ ...form, event_type: event.target.value as AttendanceEventType })
                }
              >
                <option value="clock_in">Entrada</option>
                <option value="break_start">Inicio de pausa</option>
                <option value="break_end">Fin de pausa</option>
                <option value="clock_out">Salida</option>
              </select>
            </Field>
            <Field label="Fecha y hora" required className="full">
              <input
                className="input"
                type="datetime-local"
                value={form.occurred_at}
                max={new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
                  .toISOString()
                  .slice(0, 16)}
                onChange={(event) => setForm({ ...form, occurred_at: event.target.value })}
                required
              />
            </Field>
            <Field label="Motivo" className="full" hint="Quedará en la nota del fichaje y en la auditoría.">
              <input
                className="input"
                value={form.note}
                onChange={(event) => setForm({ ...form, note: event.target.value })}
                placeholder="Olvido de tarjeta, corrección acordada…"
                maxLength={255}
              />
            </Field>
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>
    </>
  );
}
