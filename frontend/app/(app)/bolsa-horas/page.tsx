"use client";

import { useEffect, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import {
  fmtDate,
  fmtMinutes,
  fmtNumber,
  fmtSignedMinutes,
  todayMadrid,
} from "@/lib/format";
import type {
  Employee,
  HoursBankAdjustment,
  HoursBankSummary,
  Page,
} from "@/lib/types";
import {
  Badge,
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
import { IconClock, IconPlus, IconRefresh, IconTrash } from "@/components/icons";

function firstOfMonth(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

export default function HoursBankPage() {
  const toast = useToast();
  const [today, setToday] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [employeeId, setEmployeeId] = useState("");

  useEffect(() => {
    const current = todayMadrid();
    setToday(current);
    setFrom(firstOfMonth(current));
    setTo(current);
  }, []);

  const employees = useApi<Page<Employee>>("/api/v1/employees?status=active&limit=200");
  const summary = useApi<HoursBankSummary>(
    from && to
      ? withQuery("/api/v1/hours-bank", {
          date_from: from,
          date_to: to,
          employee_id: employeeId || null,
        })
      : null,
    [from, to, employeeId],
  );
  const adjustments = useApi<Page<HoursBankAdjustment>>(
    from && to
      ? withQuery("/api/v1/hours-bank/adjustments", {
          date_from: from,
          date_to: to,
          employee_id: employeeId || null,
        })
      : null,
    [from, to, employeeId],
  );

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    employee_id: "",
    effective_date: "",
    hours: "1",
    reason: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<HoursBankAdjustment | null>(null);

  const employeeOptions = employees.data?.items ?? [];
  const totals = summary.data?.totals;

  function openAdjustment() {
    setForm({
      employee_id: employeeId || "",
      effective_date: today || todayMadrid(),
      hours: "1",
      reason: "",
    });
    setError(null);
    setOpen(true);
  }

  async function createAdjustment(event: React.FormEvent) {
    event.preventDefault();
    if (!form.employee_id) {
      setError("Seleccione el trabajador.");
      return;
    }
    const hours = Number(form.hours.replace(",", "."));
    if (!Number.isFinite(hours) || hours === 0) {
      setError("Indique una cantidad de horas distinta de cero (puede ser negativa).");
      return;
    }
    if (form.reason.trim().length < 3) {
      setError("El motivo es obligatorio para que el ajuste quede justificado.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api("/api/v1/hours-bank/adjustments", {
        method: "POST",
        body: {
          employee_id: form.employee_id,
          effective_date: form.effective_date,
          minutes: Math.round(hours * 60),
          reason: form.reason.trim(),
        },
      });
      toast.success("Ajuste registrado", "Queda auditado con su usuario.");
      setOpen(false);
      summary.reload();
      adjustments.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function removeAdjustment() {
    if (!deleteTarget) return;
    setSaving(true);
    try {
      await api(`/api/v1/hours-bank/adjustments/${deleteTarget.id}`, { method: "DELETE" });
      toast.success("Ajuste eliminado", "El saldo se recalcula sobre los fichajes reales.");
      setDeleteTarget(null);
      summary.reload();
      adjustments.reload();
    } catch (err) {
      toast.error("No se pudo eliminar", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Equipo"
        title="Bolsa de horas"
        subtitle="Saldo real por trabajador: tiempo fichado menos jornada teórica del contrato, más ajustes justificados. Los fichajes nunca se editan."
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                summary.reload();
                adjustments.reload();
              }}
              disabled={saving}
            >
              <IconRefresh /> Actualizar
            </button>
            <button type="button" className="btn btn-primary" onClick={openAdjustment}>
              <IconPlus /> Nuevo ajuste
            </button>
          </>
        }
      />

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="toolbar">
          <label className="small text-muted" htmlFor="bank-from">
            Desde
          </label>
          <input
            id="bank-from"
            className="input"
            type="date"
            value={from}
            max={to || today}
            onChange={(event) => setFrom(event.target.value)}
          />
          <label className="small text-muted" htmlFor="bank-to">
            Hasta
          </label>
          <input
            id="bank-to"
            className="input"
            type="date"
            value={to}
            min={from}
            max={today}
            onChange={(event) => setTo(event.target.value)}
          />
          <select
            className="select"
            value={employeeId}
            onChange={(event) => setEmployeeId(event.target.value)}
            aria-label="Trabajador"
          >
            <option value="">Todo el equipo</option>
            {employeeOptions.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.first_name} {employee.last_name}
              </option>
            ))}
          </select>
          <span className="spacer" />
          <span className="count-chip">Periodo máximo: 93 días</span>
        </div>
      </section>

      <div className="grid grid-3" style={{ marginBottom: 18 }}>
        <Stat
          label="Horas trabajadas"
          value={fmtMinutes(totals?.worked_minutes)}
          meta={<span>fichajes reales del periodo</span>}
          accent
        />
        <Stat
          label="Jornada teórica"
          value={fmtMinutes(totals?.contracted_minutes)}
          meta={<span>prorrateada según contrato semanal</span>}
        />
        <Stat
          label="Saldo"
          value={fmtSignedMinutes(totals?.balance_minutes)}
          meta={
            <span>
              ajustes: {fmtSignedMinutes(totals?.adjustments_minutes)} ·{" "}
              {totals && totals.balance_minutes >= 0
                ? "a favor del trabajador"
                : "pendiente de compensar"}
            </span>
          }
        />
      </div>

      <section className="card" style={{ marginBottom: 18 }}>
        <div className="toolbar">
          <strong className="small">Saldo por trabajador</strong>
          <span className="spacer" />
          <span className="count-chip">
            {summary.data ? `${summary.data.items.length} trabajadores` : "—"}
          </span>
        </div>
        {summary.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={summary.error} onRetry={summary.reload} />
          </div>
        ) : null}
        {summary.loading && !summary.data ? <LoadingBlock label="Calculando saldos…" /> : null}
        {summary.data && summary.data.items.length === 0 ? (
          <EmptyState
            icon={<IconClock />}
            title="Sin trabajadores activos"
            description="Cree trabajadores y registre fichajes para calcular la bolsa de horas."
          />
        ) : null}
        {summary.data && summary.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Trabajador</th>
                  <th className="num">Contrato</th>
                  <th className="num">Días</th>
                  <th className="num">Trabajado</th>
                  <th className="num">Teórico</th>
                  <th className="num">Ajustes</th>
                  <th className="num">Saldo</th>
                </tr>
              </thead>
              <tbody>
                {summary.data.items.map((row) => (
                  <tr key={row.employee_id}>
                    <td>
                      <div className="strong small">{row.employee_name}</div>
                      <div className="tiny mono text-muted">{row.employee_code}</div>
                    </td>
                    <td className="num">{fmtNumber(row.weekly_hours, 1)} h/sem</td>
                    <td className="num">{row.days_worked}</td>
                    <td className="num">{fmtMinutes(row.worked_minutes)}</td>
                    <td className="num">{fmtMinutes(row.contracted_minutes)}</td>
                    <td className="num">{fmtSignedMinutes(row.adjustments_minutes)}</td>
                    <td className="num strong">
                      <Badge tone={row.balance_minutes >= 0 ? "success" : "danger"} dot={false}>
                        {fmtSignedMinutes(row.balance_minutes)}
                      </Badge>
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
          <strong className="small">Ajustes del periodo</strong>
          <span className="spacer" />
          <span className="count-chip">
            {adjustments.data ? `${adjustments.data.total} ajustes` : "—"}
          </span>
        </div>
        {adjustments.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={adjustments.error} onRetry={adjustments.reload} />
          </div>
        ) : null}
        {adjustments.loading && !adjustments.data ? (
          <LoadingBlock label="Cargando ajustes…" />
        ) : null}
        {adjustments.data && adjustments.data.items.length === 0 ? (
          <EmptyState
            icon={<IconPlus />}
            title="Sin ajustes"
            description="Los ajustes corrigen el saldo por compensaciones, ausencias justificadas u horas extra aprobadas."
            action={
              <button type="button" className="btn btn-ghost" onClick={openAdjustment}>
                <IconPlus /> Registrar ajuste
              </button>
            }
          />
        ) : null}
        {adjustments.data && adjustments.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Trabajador</th>
                  <th className="num">Minutos</th>
                  <th>Motivo</th>
                  <th>Registrado</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {adjustments.data.items.map((adjustment) => (
                  <tr key={adjustment.id}>
                    <td className="small nowrap">{fmtDate(adjustment.effective_date)}</td>
                    <td>
                      <div className="strong small">{adjustment.employee_name}</div>
                      <div className="tiny mono text-muted">{adjustment.employee_code}</div>
                    </td>
                    <td className="num strong">{fmtSignedMinutes(adjustment.minutes)}</td>
                    <td className="small">{adjustment.reason}</td>
                    <td className="small nowrap">{fmtDate(adjustment.created_at)}</td>
                    <td className="actions">
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={() => setDeleteTarget(adjustment)}
                      >
                        <IconTrash /> Eliminar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <Modal
        open={open}
        title="Nuevo ajuste de horas"
        subtitle="Positivo suma a favor del trabajador; negativo descuenta"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              Cancelar
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={createAdjustment}
              disabled={saving}
            >
              {saving ? <span className="spinner" /> : <IconPlus />} Registrar ajuste
            </button>
          </>
        }
      >
        {error ? (
          <div className="alert danger" style={{ marginBottom: 12 }}>
            <span>{error}</span>
          </div>
        ) : null}
        <div className="form-grid">
          <Field label="Trabajador" required>
            <select
              className="select"
              value={form.employee_id}
              onChange={(event) => setForm({ ...form, employee_id: event.target.value })}
            >
              <option value="">Seleccione…</option>
              {employeeOptions.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.code} · {employee.first_name} {employee.last_name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Fecha efectiva" required>
            <input
              className="input"
              type="date"
              value={form.effective_date}
              max={today}
              onChange={(event) => setForm({ ...form, effective_date: event.target.value })}
            />
          </Field>
          <Field label="Horas" hint="Use signo negativo para descontar. Ejemplo: 1,5 o -2" required>
            <input
              className="input"
              inputMode="decimal"
              value={form.hours}
              onChange={(event) => setForm({ ...form, hours: event.target.value })}
            />
          </Field>
          <Field label="Motivo" hint="Visible en auditoría y en el histórico" required>
            <input
              className="input"
              maxLength={255}
              value={form.reason}
              onChange={(event) => setForm({ ...form, reason: event.target.value })}
              placeholder="Compensación de horas extra aprobadas"
            />
          </Field>
        </div>
        <p className="tiny text-muted" style={{ marginTop: 10 }}>
          El ajuste no modifica los fichajes: solo corrige el saldo del periodo.
        </p>
      </Modal>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Eliminar ajuste de horas"
        message={
          <>
            Se eliminará el ajuste de{" "}
            <strong>{fmtSignedMinutes(deleteTarget?.minutes)}</strong> de{" "}
            <strong>{deleteTarget?.employee_name}</strong>. La operación queda en auditoría; el
            saldo se recalcula.
          </>
        }
        confirmLabel="Eliminar ajuste"
        danger
        busy={saving}
        onConfirm={removeAdjustment}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}
