"use client";

import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, fmtNumber } from "@/lib/format";
import type {
  Alert,
  AlertEvaluationResult,
  AlertMetric,
  AlertMetricValue,
  AlertOperator,
  AlertRule,
  AlertSeverity,
  AlertStatus,
  Page,
} from "@/lib/types";
import { useApi } from "@/lib/useApi";
import {
  Badge,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  Stat,
  useToast,
} from "@/components/ui";
import { IconAlert, IconCheck, IconPlus, IconRefresh, IconTrash } from "@/components/icons";

const OPERATORS: { value: AlertOperator; label: string }[] = [
  { value: "gt", label: "mayor que" },
  { value: "gte", label: "mayor o igual que" },
  { value: "lt", label: "menor que" },
  { value: "lte", label: "menor o igual que" },
];

const SEVERITIES: { value: AlertSeverity; label: string }[] = [
  { value: "info", label: "Informativa" },
  { value: "warning", label: "Advertencia" },
  { value: "critical", label: "Crítica" },
];

const SEVERITY_TONES = {
  info: "info",
  warning: "warning",
  critical: "danger",
} as const;

const SEVERITY_LABELS = {
  info: "Informativa",
  warning: "Advertencia",
  critical: "Crítica",
} as const;

const STATUS_LABELS: Record<AlertStatus, string> = {
  open: "Abierta",
  acknowledged: "Reconocida",
  resolved: "Resuelta",
};

const STATUS_TONES = {
  open: "danger",
  acknowledged: "warning",
  resolved: "success",
} as const;

interface FormState {
  name: string;
  metric: AlertMetric;
  operator: AlertOperator;
  threshold: string;
  severity: AlertSeverity;
  cooldown_minutes: number;
  notify_emails: string;
}

const INITIAL_FORM: FormState = {
  name: "",
  metric: "open_tasks",
  operator: "gte",
  threshold: "5",
  severity: "warning",
  cooldown_minutes: 60,
  notify_emails: "",
};

function formatValue(value: string): string {
  const numeric = Number(value);
  return fmtNumber(numeric, Number.isInteger(numeric) ? 0 : 2);
}

export function AlertsPanel() {
  const { can } = useAuth();
  const toast = useToast();
  const canManage = can("incidents.write");
  const [statusFilter, setStatusFilter] = useState<"" | AlertStatus>("open");
  const [severityFilter, setSeverityFilter] = useState<"" | AlertSeverity>("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [toDelete, setToDelete] = useState<AlertRule | null>(null);

  const query = new URLSearchParams({ limit: "100" });
  if (statusFilter) query.set("status", statusFilter);
  if (severityFilter) query.set("severity", severityFilter);

  const metrics = useApi<AlertMetricValue[]>("/api/v1/alerts/metrics");
  const alerts = useApi<Page<Alert>>(`/api/v1/alerts?${query.toString()}`);
  const rules = useApi<Page<AlertRule>>("/api/v1/alerts/rules?limit=100");

  function reload() {
    metrics.reload();
    alerts.reload();
    rules.reload();
  }

  async function evaluate() {
    setEvaluating(true);
    try {
      const result = await api<AlertEvaluationResult>("/api/v1/alerts/evaluate", {
        method: "POST",
      });
      const detail =
        result.triggered > 0
          ? `${result.triggered} alerta(s) nueva(s) de ${result.evaluated} reglas evaluadas.`
          : `Sin alertas nuevas. ${result.skipped} omitida(s) por duplicado o cooldown.`;
      toast.success("Evaluación completada", detail);
      reload();
    } catch (err) {
      toast.error("No se pudo evaluar", errorMessage(err));
    } finally {
      setEvaluating(false);
    }
  }

  async function createRule() {
    const emails = form.notify_emails
      .split(/[,;\s]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (form.name.trim().length < 3) {
      toast.error("Faltan datos", "El nombre de la regla debe tener al menos 3 caracteres.");
      return;
    }
    setSaving(true);
    try {
      await api<AlertRule>("/api/v1/alerts/rules", {
        method: "POST",
        body: {
          name: form.name.trim(),
          metric: form.metric,
          operator: form.operator,
          threshold: form.threshold,
          severity: form.severity,
          cooldown_minutes: form.cooldown_minutes,
          notify_emails: emails,
        },
      });
      toast.success("Regla creada", "Se evaluará en la próxima pasada programada.");
      setOpen(false);
      setForm(INITIAL_FORM);
      reload();
    } catch (err) {
      toast.error("No se pudo crear la regla", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function toggleRule(rule: AlertRule) {
    setBusy(rule.id);
    try {
      await api<AlertRule>(`/api/v1/alerts/rules/${rule.id}`, {
        method: "PATCH",
        body: { is_active: !rule.is_active },
      });
      toast.success(rule.is_active ? "Regla pausada" : "Regla activada");
      rules.reload();
    } catch (err) {
      toast.error("No se pudo actualizar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function deleteRule() {
    if (!toDelete) return;
    setBusy(toDelete.id);
    try {
      await api(`/api/v1/alerts/rules/${toDelete.id}`, { method: "DELETE" });
      toast.success("Regla eliminada");
      setToDelete(null);
      reload();
    } catch (err) {
      toast.error("No se pudo eliminar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function act(alert: Alert, action: "acknowledge" | "resolve") {
    setBusy(alert.id);
    try {
      await api<Alert>(`/api/v1/alerts/${alert.id}/${action}`, { method: "POST", body: {} });
      toast.success(action === "acknowledge" ? "Alerta reconocida" : "Alerta resuelta");
      reload();
    } catch (err) {
      toast.error("No se pudo actualizar la alerta", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack" style={{ gap: 18 }}>
      {metrics.error ? <ErrorBlock message={metrics.error} onRetry={metrics.reload} /> : null}

      <Card
        title="Indicadores vigilados"
        subtitle="Valores calculados en vivo sobre la base de datos operativa"
        actions={
          canManage ? (
            <button type="button" className="btn btn-primary" onClick={evaluate} disabled={evaluating}>
              {evaluating ? <span className="spinner" /> : <IconRefresh />} Evaluar ahora
            </button>
          ) : null
        }
      >
        {metrics.loading && !metrics.data ? (
          <LoadingBlock label="Calculando indicadores…" />
        ) : (
          <div className="grid grid-4">
            {(metrics.data ?? []).map((item) => (
              <Stat
                key={item.metric}
                label={item.label}
                value={formatValue(item.value)}
                meta={<span>{item.unit}</span>}
              />
            ))}
          </div>
        )}
      </Card>

      <Card
        title="Alertas"
        subtitle="Cada aviso queda registrado y requiere reconocimiento y resolución"
        actions={
          <div className="row" style={{ gap: 8 }}>
            <select
              className="input"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as "" | AlertStatus)}
              aria-label="Filtrar por estado"
            >
              <option value="">Todos los estados</option>
              <option value="open">Abiertas</option>
              <option value="acknowledged">Reconocidas</option>
              <option value="resolved">Resueltas</option>
            </select>
            <select
              className="input"
              value={severityFilter}
              onChange={(event) => setSeverityFilter(event.target.value as "" | AlertSeverity)}
              aria-label="Filtrar por severidad"
            >
              <option value="">Toda severidad</option>
              <option value="critical">Críticas</option>
              <option value="warning">Advertencias</option>
              <option value="info">Informativas</option>
            </select>
          </div>
        }
        flush
      >
        {alerts.error ? <ErrorBlock message={alerts.error} onRetry={alerts.reload} /> : null}
        {alerts.loading && !alerts.data ? <LoadingBlock label="Cargando alertas…" /> : null}
        {alerts.data && alerts.data.items.length === 0 ? (
          <EmptyState
            icon={<IconAlert />}
            title="Sin alertas con estos filtros"
            description="Cuando una regla se cumpla aparecerá aquí y se notificará por correo si tiene destinatarios."
          />
        ) : null}
        {alerts.data && alerts.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Severidad</th>
                  <th>Alerta</th>
                  <th>Regla</th>
                  <th className="num">Valor / umbral</th>
                  <th>Detectada</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {alerts.data.items.map((alert) => (
                  <tr key={alert.id}>
                    <td>
                      <Badge tone={SEVERITY_TONES[alert.severity]}>
                        {SEVERITY_LABELS[alert.severity]}
                      </Badge>
                    </td>
                    <td className="strong">
                      {alert.message}
                      {alert.note ? <div className="muted small">Nota: {alert.note}</div> : null}
                      {alert.notification_error ? (
                        <div className="muted small">Correo: {alert.notification_error}</div>
                      ) : null}
                    </td>
                    <td>{alert.rule_name ?? "—"}</td>
                    <td className="num">
                      {formatValue(alert.metric_value)} / {formatValue(alert.threshold)}
                    </td>
                    <td className="small">{fmtDateTime(alert.triggered_at)}</td>
                    <td>
                      <Badge tone={STATUS_TONES[alert.status]}>{STATUS_LABELS[alert.status]}</Badge>
                      {alert.status === "resolved" && alert.resolver_name ? (
                        <div className="muted small">por {alert.resolver_name}</div>
                      ) : null}
                    </td>
                    <td>
                      {canManage && alert.status !== "resolved" ? (
                        <div className="row" style={{ gap: 6 }}>
                          {alert.status === "open" ? (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              disabled={busy === alert.id}
                              onClick={() => act(alert, "acknowledge")}
                            >
                              Reconocer
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={busy === alert.id}
                            onClick={() => act(alert, "resolve")}
                          >
                            <IconCheck /> Resolver
                          </button>
                        </div>
                      ) : (
                        <span className="muted small">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <Card
        title="Reglas configuradas"
        subtitle="Umbrales sobre indicadores reales; el correo es opcional"
        actions={
          canManage ? (
            <button type="button" className="btn" onClick={() => setOpen(true)}>
              <IconPlus /> Nueva regla
            </button>
          ) : null
        }
        flush
      >
        {rules.error ? <ErrorBlock message={rules.error} onRetry={rules.reload} /> : null}
        {rules.loading && !rules.data ? <LoadingBlock label="Cargando reglas…" /> : null}
        {rules.data && rules.data.items.length === 0 ? (
          <EmptyState
            icon={<IconAlert />}
            title="Todavía no hay reglas"
            description="Cree una regla para vigilar tareas, incidencias, repartos o stock bajo mínimo."
          />
        ) : null}
        {rules.data && rules.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Regla</th>
                  <th>Condición</th>
                  <th>Severidad</th>
                  <th className="num">Cooldown</th>
                  <th>Destinatarios</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {rules.data.items.map((rule) => {
                  const metric = metrics.data?.find((item) => item.metric === rule.metric);
                  return (
                    <tr key={rule.id}>
                      <td className="strong">
                        {rule.name}
                        {rule.creator_name ? (
                          <div className="muted small">creada por {rule.creator_name}</div>
                        ) : null}
                      </td>
                      <td>
                        {metric?.label ?? rule.metric}{" "}
                        {OPERATORS.find((item) => item.value === rule.operator)?.label ?? rule.operator}{" "}
                        <strong>{formatValue(rule.threshold)}</strong>
                      </td>
                      <td>
                        <Badge tone={SEVERITY_TONES[rule.severity]}>
                          {SEVERITY_LABELS[rule.severity]}
                        </Badge>
                      </td>
                      <td className="num">{rule.cooldown_minutes} min</td>
                      <td className="small">
                        {rule.notify_emails.length ? rule.notify_emails.join(", ") : "Solo en la app"}
                      </td>
                      <td>
                        <Badge tone={rule.is_active ? "success" : "neutral"}>
                          {rule.is_active ? "Activa" : "Pausada"}
                        </Badge>
                      </td>
                      <td>
                        {canManage ? (
                          <div className="row" style={{ gap: 6 }}>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              disabled={busy === rule.id}
                              onClick={() => toggleRule(rule)}
                            >
                              {rule.is_active ? "Pausar" : "Activar"}
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              disabled={busy === rule.id}
                              onClick={() => setToDelete(rule)}
                              aria-label={`Eliminar ${rule.name}`}
                            >
                              <IconTrash />
                            </button>
                          </div>
                        ) : (
                          <span className="muted small">Solo lectura</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <Modal
        open={open}
        title="Nueva regla de alerta"
        subtitle="Se evalúa sobre datos reales; sin destinatarios queda solo en la aplicación"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" onClick={createRule} disabled={saving}>
              {saving ? <span className="spinner" /> : <IconPlus />} Crear regla
            </button>
          </>
        }
      >
        <div className="form-grid">
          <Field label="Nombre" required>
            <input
              className="input"
              value={form.name}
              maxLength={120}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Tareas abiertas elevadas"
            />
          </Field>
          <Field label="Indicador" required>
            <select
              className="input"
              value={form.metric}
              onChange={(event) => setForm({ ...form, metric: event.target.value as AlertMetric })}
            >
              {(metrics.data ?? []).map((item) => (
                <option key={item.metric} value={item.metric}>
                  {item.label} ({item.unit})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Condición" required>
            <div className="row" style={{ gap: 8 }}>
              <select
                className="input"
                value={form.operator}
                onChange={(event) =>
                  setForm({ ...form, operator: event.target.value as AlertOperator })
                }
              >
                {OPERATORS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              <input
                className="input"
                type="number"
                min="0"
                step="0.01"
                value={form.threshold}
                onChange={(event) => setForm({ ...form, threshold: event.target.value })}
              />
            </div>
          </Field>
          <Field label="Severidad" required>
            <select
              className="input"
              value={form.severity}
              onChange={(event) =>
                setForm({ ...form, severity: event.target.value as AlertSeverity })
              }
            >
              {SEVERITIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Cooldown"
            hint="Minutos mínimos entre dos alertas de la misma regla"
          >
            <input
              className="input"
              type="number"
              min={0}
              max={1440}
              value={form.cooldown_minutes}
              onChange={(event) =>
                setForm({ ...form, cooldown_minutes: Number(event.target.value) })
              }
            />
          </Field>
          <Field label="Destinatarios de correo" hint="Separados por comas. Opcional.">
            <input
              className="input"
              value={form.notify_emails}
              onChange={(event) => setForm({ ...form, notify_emails: event.target.value })}
              placeholder="logistica@aurora.demo, direccion@aurora.demo"
            />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={toDelete !== null}
        title="Eliminar regla"
        message={
          <>
            Se eliminará <strong>{toDelete?.name}</strong>. Si ya generó alertas, el sistema pedirá
            pausarla en lugar de borrarla para conservar la trazabilidad.
          </>
        }
        confirmLabel="Eliminar"
        danger
        busy={busy === toDelete?.id}
        onConfirm={deleteRule}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}
