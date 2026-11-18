"use client";

import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import type {
  Page,
  ReportSchedule,
  ReportScheduleConfig,
  ReportScheduleFrequency,
  ReportScheduleRun,
} from "@/lib/types";
import { useApi } from "@/lib/useApi";
import {
  Badge,
  Card,
  ConfirmDialog,
  EmptyState,
  Field,
  Modal,
  useToast,
} from "@/components/ui";
import { IconClock, IconPlus, IconRefresh, IconTrash } from "@/components/icons";

const WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const KIND_LABELS = { inventory: "Inventario", movements: "Movimientos" } as const;

function cadence(schedule: ReportSchedule): string {
  const hour = `${String(schedule.hour_utc).padStart(2, "0")}:00 UTC`;
  if (schedule.frequency === "weekly") {
    return `Semanal · ${WEEKDAYS[schedule.weekday ?? 0]} · ${hour}`;
  }
  if (schedule.frequency === "monthly") {
    return `Mensual · día ${schedule.day_of_month ?? 1} · ${hour}`;
  }
  return `Diario · ${hour}`;
}

interface FormState {
  name: string;
  report_kind: "inventory" | "movements";
  report_format: "pdf" | "xlsx" | "csv";
  frequency: ReportScheduleFrequency;
  weekday: number;
  day_of_month: number;
  hour_utc: number;
  recipients: string;
}

const INITIAL_FORM: FormState = {
  name: "",
  report_kind: "inventory",
  report_format: "pdf",
  frequency: "daily",
  weekday: 0,
  day_of_month: 1,
  hour_utc: 6,
  recipients: "",
};

export function ReportSchedules() {
  const { can } = useAuth();
  const toast = useToast();
  const list = useApi<Page<ReportSchedule>>("/api/v1/report-schedules?limit=100");
  const config = useApi<ReportScheduleConfig>("/api/v1/report-schedules/config");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<ReportSchedule | null>(null);

  const canManage = can("reports.export");
  const smtpReady = config.data?.configured === true;

  function reload() {
    list.reload();
    config.reload();
  }

  async function save() {
    const recipients = form.recipients
      .split(/[,;\s]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!form.name.trim() || recipients.length === 0) {
      toast.error("Faltan datos", "Indique un nombre y al menos un destinatario.");
      return;
    }
    setSaving(true);
    try {
      await api<ReportSchedule>("/api/v1/report-schedules", {
        method: "POST",
        body: {
          name: form.name.trim(),
          report_kind: form.report_kind,
          report_format: form.report_format,
          frequency: form.frequency,
          weekday: form.frequency === "weekly" ? form.weekday : null,
          day_of_month: form.frequency === "monthly" ? form.day_of_month : null,
          hour_utc: form.hour_utc,
          recipients,
        },
      });
      toast.success("Programación creada", "Se enviará según la cadencia indicada.");
      setOpen(false);
      setForm(INITIAL_FORM);
      reload();
    } catch (err) {
      toast.error("No se pudo crear", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function sendNow(schedule: ReportSchedule) {
    setBusy(schedule.id);
    try {
      const result = await api<ReportScheduleRun>(
        `/api/v1/report-schedules/${schedule.id}/run`,
        { method: "POST" },
      );
      toast.success("Informe enviado", result.message_id ?? "El servidor SMTP aceptó el mensaje.");
      reload();
    } catch (err) {
      toast.error("No se pudo enviar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function toggle(schedule: ReportSchedule) {
    setBusy(schedule.id);
    try {
      await api<ReportSchedule>(`/api/v1/report-schedules/${schedule.id}`, {
        method: "PATCH",
        body: { is_active: !schedule.is_active },
      });
      toast.success(schedule.is_active ? "Programación pausada" : "Programación activada");
      reload();
    } catch (err) {
      toast.error("No se pudo actualizar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!toDelete) return;
    setBusy(toDelete.id);
    try {
      await api<void>(`/api/v1/report-schedules/${toDelete.id}`, { method: "DELETE" });
      toast.success("Programación eliminada");
      setToDelete(null);
      reload();
    } catch (err) {
      toast.error("No se pudo eliminar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card
      title="Informes programados"
      subtitle="Envío por correo de PDF, Excel o CSV con cadencia diaria, semanal o mensual"
      actions={
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn btn-sm btn-ghost" onClick={reload} disabled={list.loading}>
            <IconRefresh /> Actualizar
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setOpen(true)}
            disabled={!canManage}
          >
            <IconPlus /> Nueva programación
          </button>
        </div>
      }
    >
      {!smtpReady && config.data ? (
        <div className="alert warning" style={{ marginBottom: 12 }}>
          <strong>Correo saliente sin configurar</strong>
          <span>
            Defina <code>SMTP_HOST</code>, <code>SMTP_FROM</code> y, si procede, credenciales en el
            servidor. Las programaciones se guardan, pero no se enviarán hasta configurarlo.
          </span>
        </div>
      ) : null}

      {list.error ? <div className="alert danger">{list.error}</div> : null}

      {list.data && list.data.items.length === 0 ? (
        <EmptyState
          title="Sin informes programados"
          description="Cree una programación para recibir el inventario o los movimientos por correo."
        />
      ) : null}

      {list.data && list.data.items.length > 0 ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Informe</th>
                <th>Cadencia</th>
                <th>Destinatarios</th>
                <th>Próximo envío</th>
                <th>Último resultado</th>
                <th>Estado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((schedule) => (
                <tr key={schedule.id}>
                  <td>
                    <strong>{schedule.name}</strong>
                    <div className="hint">
                      {schedule.creator_name ? `Creada por ${schedule.creator_name}` : "—"}
                    </div>
                  </td>
                  <td>
                    {KIND_LABELS[schedule.report_kind]} · {schedule.report_format.toUpperCase()}
                  </td>
                  <td>{cadence(schedule)}</td>
                  <td>
                    <span className="hint">{schedule.recipients.join(", ")}</span>
                  </td>
                  <td>{schedule.is_active ? fmtDateTime(schedule.next_run_at) : "Pausada"}</td>
                  <td>
                    {schedule.last_status === "sent" ? (
                      <Badge tone="success">Enviado {fmtDateTime(schedule.last_run_at)}</Badge>
                    ) : schedule.last_status === "failed" ? (
                      <Badge tone="danger">Error: {schedule.last_error.slice(0, 60)}</Badge>
                    ) : (
                      <span className="hint">Aún no se ha ejecutado</span>
                    )}
                  </td>
                  <td>
                    {schedule.is_active ? (
                      <Badge tone="info">Activa</Badge>
                    ) : (
                      <Badge tone="neutral">Pausada</Badge>
                    )}
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => sendNow(schedule)}
                        disabled={!canManage || !smtpReady || busy === schedule.id}
                        title={smtpReady ? "Enviar ahora" : "Configure SMTP para enviar"}
                      >
                        <IconClock /> Enviar
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => toggle(schedule)}
                        disabled={!canManage || busy === schedule.id}
                      >
                        {schedule.is_active ? "Pausar" : "Activar"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => setToDelete(schedule)}
                        disabled={!canManage || busy === schedule.id}
                        aria-label={`Eliminar ${schedule.name}`}
                      >
                        <IconTrash />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <Modal
        open={open}
        title="Nueva programación"
        subtitle="El envío real lo realiza el planificador con la configuración SMTP del servidor."
        onClose={() => setOpen(false)}
        footer={
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              Cancelar
            </button>
            <button type="button" className="btn" onClick={save} disabled={saving}>
              {saving ? <span className="spinner" /> : <IconPlus />} Crear programación
            </button>
          </div>
        }
      >
        <div className="stack" style={{ gap: 12 }}>
          <Field label="Nombre">
            <input
              className="input"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Inventario diario de compras"
            />
          </Field>
          <div className="grid grid-2" style={{ gap: 12 }}>
            <Field label="Informe">
              <select
                className="input"
                value={form.report_kind}
                onChange={(event) =>
                  setForm({ ...form, report_kind: event.target.value as FormState["report_kind"] })
                }
              >
                <option value="inventory">Inventario</option>
                <option value="movements">Movimientos</option>
              </select>
            </Field>
            <Field label="Formato">
              <select
                className="input"
                value={form.report_format}
                onChange={(event) =>
                  setForm({
                    ...form,
                    report_format: event.target.value as FormState["report_format"],
                  })
                }
              >
                <option value="pdf">PDF</option>
                <option value="xlsx">Excel</option>
                <option value="csv">CSV</option>
              </select>
            </Field>
          </div>
          <div className="grid grid-2" style={{ gap: 12 }}>
            <Field label="Cadencia">
              <select
                className="input"
                value={form.frequency}
                onChange={(event) =>
                  setForm({
                    ...form,
                    frequency: event.target.value as ReportScheduleFrequency,
                  })
                }
              >
                <option value="daily">Diaria</option>
                <option value="weekly">Semanal</option>
                <option value="monthly">Mensual</option>
              </select>
            </Field>
            <Field label="Hora UTC">
              <input
                className="input"
                type="number"
                min={0}
                max={23}
                value={form.hour_utc}
                onChange={(event) =>
                  setForm({ ...form, hour_utc: Number(event.target.value) })
                }
              />
            </Field>
          </div>
          {form.frequency === "weekly" ? (
            <Field label="Día de la semana">
              <select
                className="input"
                value={form.weekday}
                onChange={(event) => setForm({ ...form, weekday: Number(event.target.value) })}
              >
                {WEEKDAYS.map((day, index) => (
                  <option key={day} value={index}>
                    {day}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          {form.frequency === "monthly" ? (
            <Field label="Día del mes">
              <input
                className="input"
                type="number"
                min={1}
                max={28}
                value={form.day_of_month}
                onChange={(event) =>
                  setForm({ ...form, day_of_month: Number(event.target.value) })
                }
              />
            </Field>
          ) : null}
          <Field label="Destinatarios" hint="Separe varios correos con comas. Máximo 20.">
            <textarea
              className="input"
              rows={2}
              value={form.recipients}
              onChange={(event) => setForm({ ...form, recipients: event.target.value })}
              placeholder="compras@empresa.es, direccion@empresa.es"
            />
          </Field>
          <p className="hint">
            La hora se expresa en UTC (hora del almacén: Europe/Madrid). El planificador
            <code> scripts/send_scheduled_reports.py </code> debe ejecutarse cada pocos minutos.
          </p>
        </div>
      </Modal>

      <ConfirmDialog
        open={toDelete !== null}
        title="Eliminar programación"
        message={
          <>
            Se eliminará <strong>{toDelete?.name}</strong>. Los envíos ya realizados no se pueden
            deshacer.
          </>
        }
        confirmLabel="Eliminar"
        danger
        busy={busy === toDelete?.id}
        onConfirm={remove}
        onClose={() => setToDelete(null)}
      />
    </Card>
  );
}
