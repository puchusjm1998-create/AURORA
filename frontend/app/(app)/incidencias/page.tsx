"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import {
  fmtDateTime,
  incidentSeverityMeta,
  incidentStatusMeta,
  incidentTypeMeta,
} from "@/lib/format";
import type { Employee, Incident, IncidentSeverity, IncidentType, Page } from "@/lib/types";
import { LocationPicker, PalletPicker, ProductPicker } from "@/components/pickers";
import {
  Badge,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  Pagination,
  SearchInput,
  Stat,
  useToast,
} from "@/components/ui";
import { IconIncident, IconPlus, IconRefresh } from "@/components/icons";

const LIMIT = 25;
const PENDING = "open,acknowledged";

const SEVERITIES: { value: IncidentSeverity; label: string }[] = [
  { value: "low", label: "Baja" },
  { value: "medium", label: "Media" },
  { value: "high", label: "Alta" },
  { value: "critical", label: "Crítica" },
];

const TYPES: { value: IncidentType; label: string }[] = [
  { value: "damage", label: "Daño o rotura" },
  { value: "discrepancy", label: "Descuadre de stock" },
  { value: "quality", label: "Calidad" },
  { value: "safety", label: "Seguridad" },
  { value: "other", label: "Otra" },
];

export default function IncidentsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [status, setStatus] = useState(PENDING);
  const [severity, setSeverity] = useState("");
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    title: "",
    description: "",
    incident_type: "damage" as IncidentType,
    severity: "medium" as IncidentSeverity,
    assigned_to: "",
  });
  const [product, setProduct] = useState<{ id: string } | null>(null);
  const [location, setLocation] = useState<{ id: string } | null>(null);
  const [pallet, setPallet] = useState<{ id: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [resolveTarget, setResolveTarget] = useState<Incident | null>(null);
  const [resolution, setResolution] = useState("");

  const debounced = useDebounced(search, 280);
  const canWrite = can("incidents.write");
  const canReport = canWrite || can("incidents.report");
  const canAssign = can("workers.read");

  const query = useMemo(
    () =>
      withQuery("/api/v1/incidents", {
        status: status || null,
        severity: severity || null,
        incident_type: type || null,
        search: debounced || null,
        limit: LIMIT,
        offset,
      }),
    [status, severity, type, debounced, offset],
  );
  const incidents = useApi<Page<Incident>>(query);
  const openCount = useApi<Page<Incident>>("/api/v1/incidents?status=open&limit=1");
  const acknowledgedCount = useApi<Page<Incident>>(
    "/api/v1/incidents?status=acknowledged&limit=1",
  );
  const criticalCount = useApi<Page<Incident>>(
    "/api/v1/incidents?status=open,acknowledged&severity=high,critical&limit=1",
  );
  const resolvedCount = useApi<Page<Incident>>("/api/v1/incidents?status=resolved&limit=1");
  const employees = useApi<Page<Employee>>(
    canAssign ? "/api/v1/employees?status=active&limit=200" : null,
  );

  function openCreate() {
    setForm({
      title: "",
      description: "",
      incident_type: "damage",
      severity: "medium",
      assigned_to: "",
    });
    setProduct(null);
    setLocation(null);
    setPallet(null);
    setError(null);
    setOpen(true);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!form.title.trim()) {
      setError("Indique un título para la incidencia.");
      return;
    }
    setBusyId("create");
    setError(null);
    try {
      const created = await api<Incident>("/api/v1/incidents", {
        method: "POST",
        body: {
          title: form.title.trim(),
          description: form.description.trim(),
          incident_type: form.incident_type,
          severity: form.severity,
          product_id: product?.id ?? null,
          location_id: location?.id ?? null,
          pallet_id: pallet?.id ?? null,
          assigned_to: form.assigned_to || null,
        },
      });
      toast.success("Incidencia registrada", `${created.code} · ${created.title}`);
      setOpen(false);
      incidents.reload();
      openCount.reload();
      criticalCount.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function transition(incident: Incident, action: string) {
    setBusyId(incident.id);
    try {
      await api(`/api/v1/incidents/${incident.id}/${action}`, { method: "POST" });
      toast.success(
        action === "acknowledge"
          ? "Incidencia reconocida"
          : action === "close"
            ? "Incidencia cerrada"
            : "Incidencia reabierta",
        incident.code,
      );
      incidents.reload();
      openCount.reload();
      acknowledgedCount.reload();
      criticalCount.reload();
      resolvedCount.reload();
    } catch (err) {
      toast.error("No se pudo actualizar", errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function resolve(event: React.FormEvent) {
    event.preventDefault();
    if (!resolveTarget) return;
    if (resolution.trim().length < 5) {
      toast.error("Resolución demasiado corta", "Explique qué se hizo (mínimo 5 caracteres).");
      return;
    }
    setBusyId(resolveTarget.id);
    try {
      await api(`/api/v1/incidents/${resolveTarget.id}/resolve`, {
        method: "POST",
        body: { resolution: resolution.trim() },
      });
      toast.success("Incidencia resuelta", resolveTarget.code);
      setResolveTarget(null);
      setResolution("");
      incidents.reload();
      openCount.reload();
      acknowledgedCount.reload();
      resolvedCount.reload();
      criticalCount.reload();
    } catch (err) {
      toast.error("No se pudo resolver", errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Calidad y seguridad"
        title="Incidencias de almacén"
        subtitle="Registre daños, descuadres, problemas de calidad o seguridad y deje constancia de cómo se resolvieron."
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={incidents.reload}
              disabled={incidents.loading}
            >
              <IconRefresh /> Actualizar
            </button>
            {canReport ? (
              <button type="button" className="btn btn-primary" onClick={openCreate}>
                <IconPlus /> Reportar incidencia
              </button>
            ) : null}
          </>
        }
      />

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Stat
          label="Abiertas"
          value={openCount.data?.total ?? "—"}
          meta={<span>sin reconocer todavía</span>}
          accent
        />
        <Stat
          label="En gestión"
          value={acknowledgedCount.data?.total ?? "—"}
          meta={<span>reconocidas, pendientes de resolver</span>}
        />
        <Stat
          label="Alta prioridad"
          value={criticalCount.data?.total ?? "—"}
          meta={<span>severidad alta o crítica sin cerrar</span>}
        />
        <Stat
          label="Resueltas"
          value={resolvedCount.data?.total ?? "—"}
          meta={<span>pendientes de cierre definitivo</span>}
        />
      </div>

      <section className="card">
        <div className="toolbar">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder="Buscar por código, título o descripción…"
          />
          <select
            className="select"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            aria-label="Estado"
          >
            <option value={PENDING}>Pendientes</option>
            <option value="open">Abiertas</option>
            <option value="acknowledged">Reconocidas</option>
            <option value="resolved">Resueltas</option>
            <option value="closed">Cerradas</option>
            <option value="">Todas</option>
          </select>
          <select
            className="select"
            value={severity}
            onChange={(event) => {
              setSeverity(event.target.value);
              setOffset(0);
            }}
            aria-label="Severidad"
          >
            <option value="">Toda severidad</option>
            {SEVERITIES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={type}
            onChange={(event) => {
              setType(event.target.value);
              setOffset(0);
            }}
            aria-label="Tipo"
          >
            <option value="">Todo tipo</option>
            {TYPES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <span className="spacer" />
          <span className="count-chip">
            {incidents.data ? `${incidents.data.total} incidencias` : "—"}
          </span>
        </div>

        {incidents.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={incidents.error} onRetry={incidents.reload} />
          </div>
        ) : null}
        {incidents.loading && !incidents.data ? (
          <LoadingBlock label="Cargando incidencias…" />
        ) : null}
        {incidents.data && incidents.data.items.length === 0 ? (
          <EmptyState
            icon={<IconIncident />}
            title="Sin incidencias"
            description={
              canReport
                ? "No hay incidencias con estos filtros. Si algo no cuadra en el almacén, regístrelo aquí."
                : "No hay incidencias que coincidan con el filtro."
            }
            action={
              canReport ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={openCreate}>
                  Reportar incidencia
                </button>
              ) : undefined
            }
          />
        ) : null}

        {incidents.data && incidents.data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Incidencia</th>
                    <th>Tipo</th>
                    <th>Ubicación / material</th>
                    <th>Severidad</th>
                    <th>Estado</th>
                    <th>Responsable</th>
                    <th>Registrada</th>
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {incidents.data.items.map((incident) => {
                    const statusMeta = incidentStatusMeta[incident.status] ?? {
                      tone: "neutral",
                      label: incident.status,
                    };
                    const severityMeta = incidentSeverityMeta[incident.severity] ?? {
                      tone: "neutral",
                      label: incident.severity,
                    };
                    const typeMeta = incidentTypeMeta[incident.incident_type] ?? {
                      tone: "neutral",
                      label: incident.incident_type,
                    };
                    const busy = busyId === incident.id;
                    return (
                      <tr key={incident.id}>
                        <td>
                          <div className="strong small">{incident.title}</div>
                          <div className="tiny mono text-muted">{incident.code}</div>
                          {incident.description ? (
                            <div className="tiny text-muted" style={{ maxWidth: 340 }}>
                              {incident.description}
                            </div>
                          ) : null}
                          {incident.resolution ? (
                            <div className="tiny text-accent" style={{ maxWidth: 340 }}>
                              Resolución: {incident.resolution}
                            </div>
                          ) : null}
                        </td>
                        <td>
                          <Badge tone={typeMeta.tone as "warning"}>{typeMeta.label}</Badge>
                        </td>
                        <td className="small">
                          {incident.location_code ? (
                            <Link
                              href={`/ubicacion?code=${encodeURIComponent(incident.location_code)}`}
                              className="code-chip location"
                            >
                              {incident.location_code}
                            </Link>
                          ) : null}
                          {incident.product_sku ? (
                            <div className="tiny">
                              <Link href={`/producto?id=${incident.product_id}`} className="text-accent">
                                {incident.product_sku}
                              </Link>
                              {incident.product_name ? (
                                <span className="text-muted"> · {incident.product_name}</span>
                              ) : null}
                            </div>
                          ) : null}
                          {incident.pallet_code ? (
                            <div className="tiny">
                              <Link href={`/pale?id=${incident.pallet_id}`} className="text-accent">
                                {incident.pallet_code}
                              </Link>
                            </div>
                          ) : null}
                          {!incident.location_code && !incident.product_sku && !incident.pallet_code ? (
                            <span className="text-muted">—</span>
                          ) : null}
                        </td>
                        <td>
                          <Badge tone={severityMeta.tone as "danger"}>{severityMeta.label}</Badge>
                        </td>
                        <td>
                          <Badge tone={statusMeta.tone as "danger"}>{statusMeta.label}</Badge>
                          {incident.resolved_at ? (
                            <div className="tiny text-muted nowrap">
                              {fmtDateTime(incident.resolved_at)}
                            </div>
                          ) : null}
                        </td>
                        <td className="small">
                          {incident.assignee_name ?? <span className="text-muted">Sin asignar</span>}
                          <div className="tiny text-muted">
                            {incident.reported_by_name
                              ? `Reportó: ${incident.reported_by_name}`
                              : null}
                          </div>
                        </td>
                        <td className="small text-muted nowrap">{fmtDateTime(incident.created_at)}</td>
                        <td className="actions">
                          {busy ? <span className="spinner" /> : null}
                          {canWrite && incident.status === "open" ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              disabled={busy}
                              onClick={() => transition(incident, "acknowledge")}
                            >
                              Reconocer
                            </button>
                          ) : null}
                          {canWrite && ["open", "acknowledged"].includes(incident.status) ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              disabled={busy}
                              onClick={() => {
                                setResolveTarget(incident);
                                setResolution("");
                              }}
                            >
                              Resolver
                            </button>
                          ) : null}
                          {canWrite && incident.status === "resolved" ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              disabled={busy}
                              onClick={() => transition(incident, "close")}
                            >
                              Cerrar
                            </button>
                          ) : null}
                          {canWrite && ["resolved", "closed"].includes(incident.status) ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              disabled={busy}
                              onClick={() => transition(incident, "reopen")}
                            >
                              Reabrir
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination
              total={incidents.data.total}
              limit={incidents.data.limit}
              offset={incidents.data.offset}
              onChange={setOffset}
            />
          </>
        ) : null}
      </section>

      <div className="alert" style={{ marginTop: 14 }}>
        <strong>La incidencia no corrige el stock</strong>
        <span>
          Documenta el problema y su solución. Cualquier ajuste de mercancía se hace con un movimiento
          auditado en <Link href="/operaciones">Operaciones</Link>, para que el libro explique siempre
          las cantidades reales.
        </span>
      </div>

      <Modal
        open={open}
        title="Reportar incidencia"
        subtitle="Describa qué ha pasado y, si aplica, dónde"
        onClose={() => setOpen(false)}
        wide
        footer={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setOpen(false)}
              disabled={busyId === "create"}
            >
              Cancelar
            </button>
            <button
              type="submit"
              form="incident-form"
              className="btn btn-primary"
              disabled={busyId === "create"}
            >
              {busyId === "create" ? <span className="spinner" /> : <IconPlus />} Registrar incidencia
            </button>
          </>
        }
      >
        <form id="incident-form" className="stack" onSubmit={create}>
          <Field label="Título" required>
            <input
              className="input"
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="Palé dañado en el pasillo P01"
              maxLength={160}
              required
            />
          </Field>
          <div className="form-grid">
            <Field label="Tipo" required>
              <select
                className="select"
                value={form.incident_type}
                onChange={(event) =>
                  setForm({ ...form, incident_type: event.target.value as IncidentType })
                }
              >
                {TYPES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Severidad" required>
              <select
                className="select"
                value={form.severity}
                onChange={(event) =>
                  setForm({ ...form, severity: event.target.value as IncidentSeverity })
                }
              >
                {SEVERITIES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Descripción" className="full" hint="Qué ha pasado, qué material está afectado y qué se ha hecho por ahora.">
              <textarea
                className="input"
                rows={3}
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                maxLength={4000}
              />
            </Field>
            <Field label="Ubicación (opcional)">
              <LocationPicker value={location?.id ?? null} onChange={setLocation} />
            </Field>
            <Field label="Palé (opcional)">
              <PalletPicker value={pallet?.id ?? null} onChange={setPallet} />
            </Field>
            <Field label="Producto (opcional)" className="full">
              <ProductPicker value={product?.id ?? null} onChange={setProduct} />
            </Field>
            {canAssign ? (
              <Field label="Asignar a" className="full" hint="Puede dejarse sin asignar y asignarlo después.">
                <select
                  className="select"
                  value={form.assigned_to}
                  onChange={(event) => setForm({ ...form, assigned_to: event.target.value })}
                >
                  <option value="">Sin asignar</option>
                  {employees.data?.items.map((employee) => (
                    <option key={employee.id} value={employee.id}>
                      {employee.first_name} {employee.last_name} · {employee.position || employee.department}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <Modal
        open={Boolean(resolveTarget)}
        title="Resolver incidencia"
        subtitle={resolveTarget ? `${resolveTarget.code} · ${resolveTarget.title}` : undefined}
        onClose={() => setResolveTarget(null)}
        footer={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setResolveTarget(null)}
              disabled={Boolean(busyId)}
            >
              Cancelar
            </button>
            <button
              type="submit"
              form="resolve-form"
              className="btn btn-primary"
              disabled={Boolean(busyId)}
            >
              {busyId ? <span className="spinner" /> : null} Marcar como resuelta
            </button>
          </>
        }
      >
        <form id="resolve-form" className="stack" onSubmit={resolve}>
          <Field
            label="Qué se ha hecho"
            required
            hint="Quedará en el historial de la incidencia y en la auditoría."
          >
            <textarea
              className="input"
              rows={4}
              value={resolution}
              onChange={(event) => setResolution(event.target.value)}
              placeholder="Se reubicaron las cajas, se precintó un palé nuevo y se ajustó el stock con un movimiento de corrección."
              required
            />
          </Field>
        </form>
      </Modal>
    </>
  );
}
