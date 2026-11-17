"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import { fmtDate, fmtMoney, invoiceStatusMeta } from "@/lib/format";
import type { Invoice, Page, Supplier } from "@/lib/types";
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
  useToast,
} from "@/components/ui";
import { IconInvoice, IconPlus, IconRefresh } from "@/components/icons";

const LIMIT = 25;

export default function InvoicesPage() {
  const router = useRouter();
  const { can } = useAuth();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    number: "",
    invoice_date: new Date().toISOString().slice(0, 10),
    supplier_id: "",
    notes: "",
  });
  const [file, setFile] = useState<File | null>(null);
  const debounced = useDebounced(search, 280);
  const suppliers = useApi<Page<Supplier>>("/api/v1/suppliers");

  const query = useMemo(
    () =>
      withQuery("/api/v1/invoices", {
        search: debounced || null,
        status: status || null,
        limit: LIMIT,
        offset,
      }),
    [debounced, status, offset],
  );
  const invoices = useApi<Page<Invoice>>(query);

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const data = new FormData();
      data.set("number", form.number.trim());
      data.set("invoice_date", form.invoice_date);
      if (form.supplier_id) data.set("supplier_id", form.supplier_id);
      data.set("notes", form.notes);
      if (file) data.set("file", file);
      const invoice = await api<Invoice>("/api/v1/invoices", { method: "POST", body: data });
      toast.success("Factura registrada", `${invoice.number} · original conservado sin modificar.`);
      setOpen(false);
      setForm({ number: "", invoice_date: new Date().toISOString().slice(0, 10), supplier_id: "", notes: "" });
      setFile(null);
      invoices.reload();
      router.push(`/factura?id=${invoice.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Documentación"
        title="Facturas y conciliación"
        subtitle="El documento original se conserva intacto. Las líneas se contrastan con las recepciones físicas."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={invoices.reload} disabled={invoices.loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("invoices.write") ? (
              <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
                <IconPlus /> Registrar factura
              </button>
            ) : null}
          </>
        }
      />

      <div className="alert warning" style={{ marginBottom: 16 }}>
        <strong>OCR automático pendiente de proveedor</strong>
        <span>
          La extracción automática de líneas (Fase 4) requiere configurar un proveedor OCR externo. Mientras no
          esté conectado, AURORA no inventa datos: las líneas se introducen y revisan por una persona.
        </span>
      </div>

      <section className="card">
        <div className="toolbar">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder="Buscar por número de factura o archivo…"
          />
          <select
            className="select"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            aria-label="Estado de factura"
          >
            <option value="">Cualquier estado</option>
            <option value="received">Recibida</option>
            <option value="reconciled">Conciliada</option>
            <option value="discrepancy">Discrepancia</option>
            <option value="in_review">En revisión</option>
          </select>
          <span className="spacer" />
          <span className="count-chip">{invoices.data ? `${invoices.data.total} facturas` : "—"}</span>
        </div>

        {invoices.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={invoices.error} onRetry={invoices.reload} />
          </div>
        ) : null}
        {invoices.loading && !invoices.data ? <LoadingBlock label="Consultando facturas…" /> : null}
        {invoices.data && invoices.data.items.length === 0 ? (
          <EmptyState
            icon={<IconInvoice />}
            title="Sin facturas"
            description="Registra la primera factura de proveedor para conciliar cantidades facturadas con recepciones."
            action={
              can("invoices.write") ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setOpen(true)}>
                  Registrar factura
                </button>
              ) : undefined
            }
          />
        ) : null}

        {invoices.data && invoices.data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Factura</th>
                    <th>Proveedor</th>
                    <th>Fecha</th>
                    <th className="num">Líneas</th>
                    <th className="num">Total</th>
                    <th>Estado</th>
                    <th>Original</th>
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {invoices.data.items.map((invoice) => {
                    const meta = invoiceStatusMeta[invoice.status] ?? { tone: "neutral", label: invoice.status };
                    return (
                      <tr key={invoice.id}>
                        <td className="mono">
                          <Link href={`/factura?id=${invoice.id}`} className="text-accent">
                            {invoice.number}
                          </Link>
                        </td>
                        <td className="small">{invoice.supplier_name ?? "—"}</td>
                        <td className="small nowrap">{fmtDate(invoice.invoice_date)}</td>
                        <td className="num">{invoice.lines.length}</td>
                        <td className="num">{fmtMoney(invoice.total)}</td>
                        <td>
                          <Badge tone={meta.tone as "success"}>{meta.label}</Badge>
                        </td>
                        <td className="small text-muted truncate" style={{ maxWidth: 180 }}>
                          {invoice.original_filename ?? "Sin archivo"}
                        </td>
                        <td className="actions">
                          <Link href={`/factura?id=${invoice.id}`} className="btn btn-sm btn-ghost">
                            Abrir
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination total={invoices.data.total} limit={invoices.data.limit} offset={invoices.data.offset} onChange={setOffset} />
          </>
        ) : null}
      </section>

      <Modal
        open={open}
        title="Registrar factura"
        subtitle="El archivo original se almacena por año/mes/día/proveedor/factura"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="invoice-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Guardar factura
            </button>
          </>
        }
      >
        <form id="invoice-form" className="stack" onSubmit={upload}>
          <div className="form-grid">
            <Field label="Número de factura" required>
              <input
                className="input mono"
                value={form.number}
                onChange={(event) => setForm({ ...form, number: event.target.value })}
                required
                placeholder="TPK-2026/1180"
              />
            </Field>
            <Field label="Fecha de factura" required>
              <input
                className="input"
                type="date"
                value={form.invoice_date}
                onChange={(event) => setForm({ ...form, invoice_date: event.target.value })}
                required
              />
            </Field>
            <Field label="Proveedor" className="full">
              <select
                className="select"
                value={form.supplier_id}
                onChange={(event) => setForm({ ...form, supplier_id: event.target.value })}
              >
                <option value="">Sin proveedor</option>
                {suppliers.data?.items.map((supplier) => (
                  <option key={supplier.id} value={supplier.id}>
                    {supplier.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Documento original"
              className="full"
              hint="PDF, JPG, PNG, WEBP o TIFF (máx. 25 MB). Se guarda sin modificaciones y con verificación SHA-256."
            >
              <input
                className="input"
                type="file"
                accept="application/pdf,image/jpeg,image/png,image/webp,image/tiff"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </Field>
            <Field label="Observaciones" className="full">
              <textarea
                className="textarea"
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
              />
            </Field>
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>
    </>
  );
}
