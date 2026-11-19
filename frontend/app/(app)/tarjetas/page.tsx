"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { fmtDateTime } from "@/lib/format";
import { webNfcSupported, writeNfcToken } from "@/lib/nfc";
import type { Employee, NfcCard, NfcCardIssued, Page } from "@/lib/types";
import {
  Badge,
  ConfirmDialog,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  useToast,
} from "@/components/ui";
import { IconNfc, IconPlus, IconQr, IconRefresh, IconTrash } from "@/components/icons";

export default function NfcCardsPage() {
  const toast = useToast();
  const [employeeId, setEmployeeId] = useState("");
  const [status, setStatus] = useState("");
  const cards = useApi<Page<NfcCard>>(
    withQuery("/api/v1/nfc/cards", {
      employee_id: employeeId || null,
      status: status || null,
      limit: 200,
    }),
    [employeeId, status],
  );
  const employees = useApi<Page<Employee>>("/api/v1/employees?status=active&limit=200");

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ employee_id: "", label: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<NfcCardIssued | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<NfcCard | null>(null);
  const [nfcSupported, setNfcSupported] = useState(false);
  const [writing, setWriting] = useState(false);
  const [writeError, setWriteError] = useState<string | null>(null);

  useEffect(() => {
    setNfcSupported(webNfcSupported());
  }, []);

  const employeeOptions = employees.data?.items ?? [];
  const activeCards = useMemo(
    () => cards.data?.items.filter((card) => card.status === "active").length ?? 0,
    [cards.data],
  );

  function openIssue() {
    setForm({ employee_id: "", label: "" });
    setError(null);
    setOpen(true);
  }

  async function issue(event: React.FormEvent) {
    event.preventDefault();
    if (!form.employee_id) {
      setError("Seleccione el trabajador.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const card = await api<NfcCardIssued>("/api/v1/nfc/cards", {
        method: "POST",
        body: {
          employee_id: form.employee_id,
          label: form.label.trim(),
        },
      });
      setOpen(false);
      setIssued(card);
      setWriteError(null);
      cards.reload();
      toast.success("Tarjeta emitida", "Guarde o grabe el token ahora: no se volverá a mostrar.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function revoke() {
    if (!revokeTarget) return;
    setSaving(true);
    try {
      await api(`/api/v1/nfc/cards/${revokeTarget.id}/revoke`, { method: "POST" });
      toast.success("Tarjeta revocada", "Ya no puede registrar fichajes.");
      setRevokeTarget(null);
      cards.reload();
    } catch (err) {
      toast.error("No se pudo revocar", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function writeTag() {
    if (!issued) return;
    setWriting(true);
    setWriteError(null);
    try {
      await writeNfcToken(issued.token);
      toast.success(
        "Etiqueta grabada",
        "Acerque esta etiqueta al lector NFC para fichar.",
      );
    } catch (err) {
      setWriteError(
        err instanceof Error
          ? err.message
          : "No se pudo grabar la etiqueta. Compruebe el permiso NFC y que esté cerca.",
      );
    } finally {
      setWriting(false);
    }
  }

  async function copyToken() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.token);
      toast.success("Token copiado", "Entréguelo al trabajador por un canal seguro.");
    } catch {
      toast.error("No se pudo copiar", "Seleccione el token y cópielo manualmente.");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Equipo"
        title="Tarjetas NFC"
        subtitle="Emisión y revocación de tarjetas para fichar. Solo se guarda el hash SHA-256 del token; el token completo se muestra una única vez."
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => cards.reload()}
              disabled={saving}
            >
              <IconRefresh /> Actualizar
            </button>
            <button type="button" className="btn btn-primary" onClick={openIssue}>
              <IconPlus /> Emitir tarjeta
            </button>
          </>
        }
      />

      <div className="alert info" style={{ marginBottom: 16 }}>
        <span>
          Una tarjeta activa por trabajador. Grabe el token en una etiqueta NDEF desde esta página
          (Web NFC en Chrome Android) y use el <Link href="/lector">lector NFC</Link> para fichar; también
          se admite un lector USB en modo teclado.
        </span>
      </div>

      <section className="card">
        <div className="toolbar">
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
          <select
            className="select"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            aria-label="Estado"
          >
            <option value="">Todos los estados</option>
            <option value="active">Activas</option>
            <option value="revoked">Revocadas</option>
          </select>
          <span className="spacer" />
          <span className="count-chip">{activeCards} activas</span>
          <span className="count-chip">{cards.data ? `${cards.data.total} tarjetas` : "—"}</span>
        </div>

        {cards.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={cards.error} onRetry={cards.reload} />
          </div>
        ) : null}
        {cards.loading && !cards.data ? <LoadingBlock label="Cargando tarjetas…" /> : null}
        {cards.data && cards.data.items.length === 0 ? (
          <EmptyState
            icon={<IconQr />}
            title="Sin tarjetas"
            description="Emita una tarjeta para que el trabajador pueda fichar con ella."
            action={
              <button type="button" className="btn btn-primary" onClick={openIssue}>
                <IconPlus /> Emitir tarjeta
              </button>
            }
          />
        ) : null}
        {cards.data && cards.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Trabajador</th>
                  <th>Etiqueta</th>
                  <th>Token</th>
                  <th>Estado</th>
                  <th>Último uso</th>
                  <th>Emitida</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {cards.data.items.map((card) => (
                  <tr key={card.id}>
                    <td>
                      <div className="strong small">{card.employee_name}</div>
                      <div className="tiny mono text-muted">{card.employee_code}</div>
                    </td>
                    <td className="small">{card.label}</td>
                    <td className="mono small">•••• {card.token_last4}</td>
                    <td>
                      <Badge tone={card.status === "active" ? "success" : "danger"}>
                        {card.status === "active" ? "Activa" : "Revocada"}
                      </Badge>
                    </td>
                    <td className="small nowrap">{fmtDateTime(card.last_used_at)}</td>
                    <td className="small nowrap">{fmtDateTime(card.created_at)}</td>
                    <td className="actions">
                      {card.status === "active" ? (
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          onClick={() => setRevokeTarget(card)}
                        >
                          <IconTrash /> Revocar
                        </button>
                      ) : (
                        <span className="tiny text-muted nowrap">
                          {fmtDateTime(card.revoked_at)}
                        </span>
                      )}
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
        title="Emitir tarjeta NFC"
        subtitle="El token se genera en el servidor y solo se mostrará una vez"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" onClick={issue} disabled={saving}>
              {saving ? <span className="spinner" /> : <IconPlus />} Emitir tarjeta
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
          <Field label="Etiqueta" hint="Por ejemplo: llavero azul, tarjeta turno tarde">
            <input
              className="input"
              maxLength={80}
              value={form.label}
              onChange={(event) => setForm({ ...form, label: event.target.value })}
              placeholder="Llavero azul"
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={issued !== null}
        title="Tarjeta emitida"
        subtitle="Este token no vuelve a mostrarse. Guárdelo antes de cerrar."
        onClose={() => setIssued(null)}
        footer={
          <>
            {nfcSupported ? (
              <button type="button" className="btn btn-ghost" onClick={writeTag} disabled={writing}>
                {writing ? <span className="spinner" /> : <IconNfc />} Grabar en etiqueta NFC
              </button>
            ) : null}
            <button type="button" className="btn btn-ghost" onClick={copyToken}>
              Copiar token
            </button>
            <button type="button" className="btn btn-primary" onClick={() => setIssued(null)}>
              He guardado el token
            </button>
          </>
        }
      >
        {issued ? (
          <>
            <div className="alert warning" style={{ marginBottom: 12 }}>
              <strong>{issued.employee_name}</strong>
              <span>{issued.label}</span>
            </div>
            <div
              className="mono"
              style={{
                padding: 14,
                borderRadius: 8,
                border: "1px dashed var(--border)",
                wordBreak: "break-all",
                fontSize: 14,
                background: "var(--surface-2, rgba(0,0,0,0.03))",
              }}
            >
              {issued.token}
            </div>
            <p className="small text-muted" style={{ marginTop: 10 }}>
              En la base de datos solo queda el hash y los últimos cuatro caracteres (••••{" "}
              {issued.token_last4}). Si se pierde, revoque la tarjeta y emita otra.
            </p>
            {nfcSupported ? (
              <p className="small text-muted" style={{ marginTop: 8 }}>
                «Grabar en etiqueta NFC» escribe el token como texto NDEF. Acerque una etiqueta
                virgen y manténgala hasta que termine. No grabe etiquetas de pago o acceso ajenas.
              </p>
            ) : (
              <div className="alert warning" style={{ marginTop: 10 }}>
                <span>
                  Este navegador no soporta Web NFC. Use Chrome para Android sobre HTTPS para
                  grabar la etiqueta, o entregue el token a un lector USB que lo escriba como
                  teclado.
                </span>
              </div>
            )}
            {writeError ? (
              <div className="alert danger" style={{ marginTop: 10 }}>
                <span>{writeError}</span>
              </div>
            ) : null}
          </>
        ) : null}
      </Modal>

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revocar tarjeta NFC"
        message={
          <>
            La tarjeta de <strong>{revokeTarget?.employee_name}</strong> dejará de permitir
            fichajes inmediatamente. El histórico de fichajes se conserva.
          </>
        }
        confirmLabel="Revocar tarjeta"
        danger
        busy={saving}
        onConfirm={revoke}
        onClose={() => setRevokeTarget(null)}
      />
    </>
  );
}
