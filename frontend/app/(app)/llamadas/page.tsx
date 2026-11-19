"use client";

import { useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { fmtDateTime } from "@/lib/format";
import type { CallRecord, CallStatus, Page, TelephonyStatus } from "@/lib/types";
import {
  Badge,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  useToast,
} from "@/components/ui";
import { IconCheck, IconPhone, IconRefresh, IconTrash } from "@/components/icons";

const STATUS_META: Record<CallStatus, { label: string; tone: string }> = {
  handoff: { label: "Handoff", tone: "info" },
  queued: { label: "En cola", tone: "warning" },
  in_progress: { label: "En curso", tone: "info" },
  completed: { label: "Completada", tone: "success" },
  failed: { label: "Fallida", tone: "danger" },
};

export default function CallsPage() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const calls = useApi<Page<CallRecord>>(
    withQuery("/api/v1/calls", {
      status: status || null,
      search: search.trim() || null,
      limit: 100,
    }),
    [status, search],
  );
  const config = useApi<TelephonyStatus>("/api/v1/calls/config");

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ contact_name: "", phone: "", purpose: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState<{ call: CallRecord; status: "completed" | "failed" } | null>(
    null,
  );
  const [result, setResult] = useState("");

  function openNew() {
    setForm({ contact_name: "", phone: "", purpose: "" });
    setError(null);
    setOpen(true);
  }

  async function createCall(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const call = await api<CallRecord>("/api/v1/calls", {
        method: "POST",
        body: {
          contact_name: form.contact_name.trim(),
          phone: form.phone.trim(),
          purpose: form.purpose.trim(),
        },
      });
      setOpen(false);
      calls.reload();
      toast.success(
        call.status === "handoff" ? "Llamada preparada" : "Llamada enviada al proveedor",
        call.sip_uri ?? call.tel_uri,
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function closeCall(event: React.FormEvent) {
    event.preventDefault();
    if (!closing) return;
    setSaving(true);
    setError(null);
    try {
      await api(`/api/v1/calls/${closing.call.id}`, {
        method: "PATCH",
        body: { status: closing.status, result: result.trim() },
      });
      toast.success(
        closing.status === "completed" ? "Llamada completada" : "Llamada marcada como fallida",
        closing.call.contact_name,
      );
      setClosing(null);
      setResult("");
      calls.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Gestión"
        title="Llamadas"
        subtitle="Registro de llamadas con enlace tel:/sip: al softphone o marcador. No se guarda audio; el estado refleja lo que confirma el proveedor."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => calls.reload()}>
              <IconRefresh /> Actualizar
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={openNew}
              disabled={config.data?.mode === "disabled"}
            >
              <IconPhone /> Nueva llamada
            </button>
          </>
        }
      />

      {config.data ? (
        <div className={`alert ${config.data.mode === "disabled" ? "warning" : "info"}`} style={{ marginBottom: 16 }}>
          <strong>
            Modo {config.data.mode}
            {config.data.sip_domain ? ` · ${config.data.sip_domain}` : ""}
          </strong>
          <span>{config.data.message}</span>
        </div>
      ) : null}

      <section className="card">
        <div className="toolbar">
          <input
            className="input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar por contacto o teléfono"
            aria-label="Buscar llamadas"
          />
          <select
            className="select"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            aria-label="Estado"
          >
            <option value="">Todos los estados</option>
            {Object.entries(STATUS_META).map(([value, meta]) => (
              <option key={value} value={value}>
                {meta.label}
              </option>
            ))}
          </select>
          <span className="spacer" />
          <span className="count-chip">{calls.data ? `${calls.data.total} llamadas` : "—"}</span>
        </div>

        {calls.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={calls.error} onRetry={calls.reload} />
          </div>
        ) : null}
        {calls.loading && !calls.data ? <LoadingBlock label="Cargando llamadas…" /> : null}
        {calls.data && calls.data.items.length === 0 ? (
          <EmptyState
            icon={<IconPhone />}
            title="Sin llamadas registradas"
            description="Registre una llamada para dejar constancia del contacto y abrir el marcador."
            action={
              <button type="button" className="btn btn-primary" onClick={openNew}>
                <IconPhone /> Nueva llamada
              </button>
            }
          />
        ) : null}
        {calls.data && calls.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Contacto</th>
                  <th>Teléfono</th>
                  <th>Motivo</th>
                  <th>Estado</th>
                  <th>Proveedor</th>
                  <th>Creada</th>
                  <th>Resultado</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {calls.data.items.map((call) => {
                  const meta = STATUS_META[call.status] ?? { label: call.status, tone: "neutral" };
                  const terminal = call.status === "completed" || call.status === "failed";
                  return (
                    <tr key={call.id}>
                      <td>
                        <div className="strong small">{call.contact_name}</div>
                        <div className="tiny text-muted">{call.authorized_by ?? "—"}</div>
                      </td>
                      <td className="mono small nowrap">{call.phone}</td>
                      <td className="small">{call.purpose || "—"}</td>
                      <td>
                        <Badge tone={meta.tone as "info"}>{meta.label}</Badge>
                      </td>
                      <td className="small">
                        {call.provider ?? "—"}
                        {call.provider_call_id ? (
                          <div className="tiny mono text-muted">{call.provider_call_id}</div>
                        ) : null}
                      </td>
                      <td className="small nowrap">{fmtDateTime(call.created_at)}</td>
                      <td className="small">{call.result || "—"}</td>
                      <td className="actions">
                        <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                          <a
                            className="btn btn-sm btn-primary"
                            href={call.dial_uri}
                            title={call.sip_uri ? "Abrir softphone SIP" : "Abrir marcador"}
                          >
                            <IconPhone /> {call.sip_uri ? "SIP" : "Llamar"}
                          </a>
                          {!terminal ? (
                            <>
                              <button
                                type="button"
                                className="btn btn-sm btn-ghost"
                                onClick={() => {
                                  setClosing({ call, status: "completed" });
                                  setResult("");
                                  setError(null);
                                }}
                              >
                                <IconCheck /> Cerrar
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm btn-danger"
                                onClick={() => {
                                  setClosing({ call, status: "failed" });
                                  setResult("");
                                  setError(null);
                                }}
                              >
                                <IconTrash /> Fallida
                              </button>
                            </>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <Modal
        open={open}
        title="Nueva llamada"
        subtitle="Se registra el contacto y se abre el marcador o se envía al proveedor"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" onClick={createCall} disabled={saving}>
              {saving ? <span className="spinner" /> : <IconPhone />} Registrar llamada
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
          <Field label="Contacto" required>
            <input
              className="input"
              value={form.contact_name}
              onChange={(event) => setForm({ ...form, contact_name: event.target.value })}
              maxLength={120}
              required
            />
          </Field>
          <Field label="Teléfono" required>
            <input
              className="input"
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
              placeholder="+34 600 123 456"
              maxLength={32}
              required
            />
          </Field>
          <Field label="Motivo" className="full" hint="Visible en el historial y la auditoría">
            <input
              className="input"
              value={form.purpose}
              onChange={(event) => setForm({ ...form, purpose: event.target.value })}
              maxLength={255}
            />
          </Field>
        </div>
        <p className="tiny text-muted" style={{ marginTop: 10 }}>
          {config.data?.mode === "webhook"
            ? "El servidor enviará la orden al proveedor configurado; el estado inicial será el que confirme."
            : "El servidor no origina la llamada: el botón de la tabla abre tel: o sip: en su dispositivo."}
        </p>
      </Modal>

      <Modal
        open={closing !== null}
        title={closing?.status === "completed" ? "Cerrar llamada" : "Llamada fallida"}
        subtitle={closing?.call.contact_name}
        onClose={() => setClosing(null)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setClosing(null)}>
              Cancelar
            </button>
            <button
              type="button"
              className={`btn ${closing?.status === "completed" ? "btn-primary" : "btn-danger"}`}
              onClick={closeCall}
              disabled={saving}
            >
              {saving ? <span className="spinner" /> : <IconCheck />} Guardar
            </button>
          </>
        }
      >
        {error ? (
          <div className="alert danger" style={{ marginBottom: 12 }}>
            <span>{error}</span>
          </div>
        ) : null}
        <Field label="Resultado" hint="Qué se acordó o por qué no se pudo llamar">
          <textarea
            className="input"
            rows={4}
            value={result}
            onChange={(event) => setResult(event.target.value)}
            maxLength={2000}
          />
        </Field>
      </Modal>
    </>
  );
}
