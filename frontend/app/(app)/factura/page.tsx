"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, downloadFile, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { fmtDate, fmtDateTime, fmtMoney, fmtNumber, invoiceStatusMeta } from "@/lib/format";
import type { Invoice, Product } from "@/lib/types";
import { LocationPicker, ProductPicker } from "@/components/pickers";
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
  useToast,
} from "@/components/ui";
import {
  IconArrowIn,
  IconCheck,
  IconDownload,
  IconInvoice,
  IconPlus,
  IconRefresh,
  IconTrash,
} from "@/components/icons";

function InvoiceDetail() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const { can } = useAuth();
  const toast = useToast();
  const invoice = useApi<Invoice>(id ? `/api/v1/invoices/${id}` : null, [id]);
  const [lineOpen, setLineOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    product_id: "",
    description: "",
    quantity: "1",
    unit_price: "0",
    discount_pct: "0",
    tax_rate: "21",
  });
  const [product, setProduct] = useState<Product | null>(null);
  const [receiveLine, setReceiveLine] = useState<Invoice["lines"][number] | null>(null);
  const [receiveQty, setReceiveQty] = useState("");
  const [receiveLocation, setReceiveLocation] = useState<{ id: string; code: string } | null>(null);
  const [reconcileOpen, setReconcileOpen] = useState(false);
  const [deleteLine, setDeleteLine] = useState<Invoice["lines"][number] | null>(null);

  const data = invoice.data;

  async function addLine(event: React.FormEvent) {
    event.preventDefault();
    if (!data) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/v1/invoices/${data.id}/lines`, {
        method: "POST",
        body: {
          product_id: product?.id ?? null,
          supplier_ref: product?.manufacturer_ref ?? null,
          description: form.description || product?.name || "Línea de factura",
          quantity: form.quantity,
          unit_price: form.unit_price,
          discount_pct: form.discount_pct,
          tax_rate: form.tax_rate,
        },
      });
      toast.success("Línea añadida");
      setLineOpen(false);
      setProduct(null);
      setForm({ product_id: "", description: "", quantity: "1", unit_price: "0", discount_pct: "0", tax_rate: "21" });
      invoice.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function doReceive(event: React.FormEvent) {
    event.preventDefault();
    if (!data || !receiveLine || !receiveLocation) return;
    if (!receiveLine.product_id) {
      toast.error("La línea no tiene producto asociado", "Asocia un producto del catálogo para poder recibirla.");
      return;
    }
    setBusy(true);
    try {
      await api("/api/v1/movements", {
        method: "POST",
        body: {
          movement_type: "reception",
          product_id: receiveLine.product_id,
          quantity: receiveQty,
          to_location_id: receiveLocation.id,
          invoice_id: data.id,
          invoice_line_id: receiveLine.id,
          reason: `Recepción factura ${data.number}`,
          document_ref: data.number,
          confirm: true,
          physical_confirmed: true,
        },
      });
      toast.success("Recepción registrada", `${fmtNumber(receiveQty, 3)} uds · factura ${data.number}`);
      setReceiveLine(null);
      setReceiveLocation(null);
      setReceiveQty("");
      invoice.reload();
    } catch (err) {
      toast.error("No se pudo registrar la recepción", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function reconcile() {
    if (!data) return;
    setBusy(true);
    try {
      const result = await api<Invoice>(`/api/v1/invoices/${data.id}/reconcile`, { method: "POST" });
      toast.success(
        result.status === "reconciled" ? "Factura conciliada" : "Discrepancia detectada",
        result.status === "reconciled"
          ? "Todas las cantidades coinciden con las recepciones."
          : "Hay líneas pendientes o con diferencias que requieren revisión humana.",
      );
      setReconcileOpen(false);
      invoice.reload();
    } catch (err) {
      toast.error("No se pudo conciliar", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeLine() {
    if (!data || !deleteLine) return;
    setBusy(true);
    try {
      await api(`/api/v1/invoices/${data.id}/lines/${deleteLine.id}`, { method: "DELETE" });
      toast.success("Línea eliminada");
      setDeleteLine(null);
      invoice.reload();
    } catch (err) {
      toast.error("No se pudo eliminar", errorMessage(err));
      setDeleteLine(null);
    } finally {
      setBusy(false);
    }
  }

  if (!id) {
    return <EmptyState title="Factura no indicada" action={<Link href="/facturas" className="btn btn-primary btn-sm">Ver facturas</Link>} />;
  }
  if (invoice.error) return <ErrorBlock message={invoice.error} onRetry={invoice.reload} />;
  if (invoice.loading || !data) return <LoadingBlock label="Cargando factura…" />;

  const meta = invoiceStatusMeta[data.status] ?? { tone: "neutral", label: data.status };
  const pendingLines = data.lines.filter((line) => Number(line.received_quantity) < Number(line.quantity));

  return (
    <>
      <PageHeader
        eyebrow="Factura de proveedor"
        title={data.number}
        subtitle={`${data.supplier_name ?? "Sin proveedor"} · ${fmtDate(data.invoice_date)} · estado ${meta.label}`}
        actions={
          <>
            <Link href="/facturas" className="btn btn-ghost">
              <IconInvoice /> Facturas
            </Link>
            {data.file_path ? (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={async () => {
                  try {
                    await downloadFile(`/api/v1/invoices/${data.id}/file`, data.original_filename ?? "factura");
                  } catch (err) {
                    toast.error("No se pudo descargar", errorMessage(err));
                  }
                }}
              >
                <IconDownload /> Original
              </button>
            ) : null}
            {can("invoices.reconcile") ? (
              <button type="button" className="btn btn-primary" onClick={() => setReconcileOpen(true)}>
                <IconCheck /> Conciliar
              </button>
            ) : null}
          </>
        }
      />

      <div className="grid" style={{ gap: 18 }}>
        <div className="detail-hero">
          <div className="title-row">
            <div style={{ flex: 1, minWidth: 240 }}>
              <div className="row" style={{ gap: 8, marginBottom: 6 }}>
                <span className="sku">{data.number}</span>
                <Badge tone={meta.tone as "success"}>{meta.label}</Badge>
                <Badge tone="warning" dot={false}>OCR: {data.ocr_status}</Badge>
              </div>
              <h1>{data.supplier_name ?? "Factura sin proveedor"}</h1>
              <div className="detail-meta" style={{ marginTop: 8 }}>
                <span>Fecha: <b>{fmtDate(data.invoice_date)}</b></span>
                <span>Líneas: <b>{data.lines.length}</b></span>
                <span>Conciliada: <b>{data.reconciled_at ? fmtDateTime(data.reconciled_at) : "pendiente"}</b></span>
                {data.file_sha256 ? <span>SHA-256: <b className="mono tiny">{data.file_sha256.slice(0, 16)}…</b></span> : null}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="kpi-label">Total factura</div>
              <div style={{ fontSize: 30, fontWeight: 700 }}>{fmtMoney(data.total)}</div>
              <div className="small text-muted">
                Base {fmtMoney(data.subtotal)} · IVA {fmtMoney(data.tax_total)}
              </div>
            </div>
          </div>
          {data.notes ? <p className="small text-soft">{data.notes}</p> : null}
          {data.original_filename ? (
            <p className="small text-muted">
              Original conservado: <span className="mono">{data.original_filename}</span>
            </p>
          ) : (
            <p className="small text-muted">Factura registrada sin documento adjunto (entrada manual).</p>
          )}
        </div>

        <Card
          title="Líneas de factura"
          subtitle="Cantidad facturada frente a cantidad recibida físicamente"
          flush
          actions={
            can("invoices.write") ? (
              <button type="button" className="btn btn-sm btn-primary" onClick={() => setLineOpen(true)}>
                <IconPlus /> Añadir línea
              </button>
            ) : null
          }
        >
          {data.lines.length === 0 ? (
            <EmptyState
              icon={<IconInvoice />}
              title="Sin líneas"
              description="Añade las líneas manualmente o configura el proveedor OCR en la Fase 4."
              action={
                can("invoices.write") ? (
                  <button type="button" className="btn btn-sm btn-primary" onClick={() => setLineOpen(true)}>
                    Añadir línea
                  </button>
                ) : undefined
              }
            />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Descripción</th>
                    <th>Producto</th>
                    <th className="num">Cantidad</th>
                    <th className="num">Precio</th>
                    <th className="num">Dto.</th>
                    <th className="num">IVA</th>
                    <th className="num">Total</th>
                    <th className="num">Recibido</th>
                    <th />
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.lines.map((line) => {
                    const remaining = Number(line.quantity) - Number(line.received_quantity);
                    return (
                      <tr key={line.id}>
                        <td className="mono">{line.line_number}</td>
                        <td>
                          <div className="small strong">{line.description}</div>
                          {line.supplier_ref ? <div className="tiny mono text-muted">{line.supplier_ref}</div> : null}
                        </td>
                        <td>
                          {line.product_id ? (
                            <Link href={`/producto?id=${line.product_id}`} className="small text-accent">
                              {line.product_name ?? line.product_sku}
                            </Link>
                          ) : (
                            <Badge tone="warning" dot={false}>Sin asociar</Badge>
                          )}
                        </td>
                        <td className="num">{fmtNumber(line.quantity, 3)}</td>
                        <td className="num">{fmtMoney(line.unit_price)}</td>
                        <td className="num">{fmtNumber(line.discount_pct, 1)}%</td>
                        <td className="num">{fmtNumber(line.tax_rate, 0)}%</td>
                        <td className="num">{fmtMoney(line.line_total)}</td>
                        <td className="num">
                          {fmtNumber(line.received_quantity, 3)}
                          {line.review_required ? (
                            <div className="tiny text-danger">revisar</div>
                          ) : remaining > 0 ? (
                            <div className="tiny text-warning">pendiente {fmtNumber(remaining, 2)}</div>
                          ) : (
                            <div className="tiny text-success">completo</div>
                          )}
                        </td>
                        <td>
                          {can("invoices.write") && line.product_id && remaining > 0 ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => {
                                setReceiveLine(line);
                                setReceiveQty(String(remaining));
                              }}
                              title="Registrar recepción de esta línea"
                            >
                              <IconArrowIn /> Recibir
                            </button>
                          ) : null}
                        </td>
                        <td className="actions">
                          {can("invoices.write") && Number(line.received_quantity) === 0 ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => setDeleteLine(line)}
                              aria-label="Eliminar línea"
                            >
                              <IconTrash />
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={7} style={{ textAlign: "right" }}>Base imponible</td>
                    <td className="num" colSpan={3}>{fmtMoney(data.subtotal)}</td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={7} style={{ textAlign: "right" }}>IVA</td>
                    <td className="num" colSpan={3}>{fmtMoney(data.tax_total)}</td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={7} style={{ textAlign: "right" }}>Total</td>
                    <td className="num" colSpan={3}>{fmtMoney(data.total)}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </Card>

        <div className="split">
          <Card title="Conciliación" subtitle="Comprueba si lo facturado coincide con lo recibido">
            <div className="stack" style={{ gap: 10 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="small text-muted">Líneas completas</span>
                <span className="strong">
                  {data.lines.length - pendingLines.length} / {data.lines.length}
                </span>
              </div>
              <div className={`progress${pendingLines.length ? " warn" : ""}`}>
                <i
                  style={{
                    width: `${data.lines.length ? ((data.lines.length - pendingLines.length) / data.lines.length) * 100 : 0}%`,
                  }}
                />
              </div>
              {pendingLines.length ? (
                <div className="alert warning">
                  <strong>{pendingLines.length} línea(s) pendiente(s)</strong>
                  <span>
                    Diferencias detectadas entre factura y recepción física. Requiere revisión humana antes de
                    cerrar la factura.
                  </span>
                </div>
              ) : (
                <div className="alert success">
                  <strong>Todo recibido</strong>
                  <span>Las cantidades facturadas coinciden con las recepciones registradas.</span>
                </div>
              )}
              {can("invoices.reconcile") ? (
                <button type="button" className="btn btn-primary" onClick={() => setReconcileOpen(true)}>
                  <IconRefresh /> Recalcular conciliación
                </button>
              ) : null}
            </div>
          </Card>

          <div className="side-panel">
            <div className="alert">
              <strong>Documento inmutable</strong>
              <span>
                AURORA nunca modifica el archivo original. Cualquier dato extraído o introducido se guarda en la
                base de datos y queda auditado con su autor y fecha.
              </span>
            </div>
          </div>
        </div>
      </div>

      <Modal
        open={lineOpen}
        title="Añadir línea de factura"
        onClose={() => setLineOpen(false)}
        wide
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setLineOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="line-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Añadir línea
            </button>
          </>
        }
      >
        <form id="line-form" className="stack" onSubmit={addLine}>
          <Field label="Producto del catálogo" hint="Opcional, pero necesario para conciliar y recibir">
            <ProductPicker
              value={product?.id ?? null}
              onChange={(value) => {
                setProduct(value);
                if (value && !form.description) {
                  setForm((current) => ({ ...current, description: value.name, unit_price: String(value.purchase_price) }));
                }
              }}
            />
          </Field>
          <Field label="Descripción facturada" required>
            <input
              className="input"
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              required
            />
          </Field>
          <div className="form-grid">
            <Field label="Cantidad" required>
              <input
                className="input"
                type="number"
                min="0.001"
                step="0.001"
                value={form.quantity}
                onChange={(event) => setForm({ ...form, quantity: event.target.value })}
                required
              />
            </Field>
            <Field label="Precio unitario (€)" required>
              <input
                className="input"
                type="number"
                min="0"
                step="0.0001"
                value={form.unit_price}
                onChange={(event) => setForm({ ...form, unit_price: event.target.value })}
                required
              />
            </Field>
            <Field label="Descuento (%)">
              <input
                className="input"
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={form.discount_pct}
                onChange={(event) => setForm({ ...form, discount_pct: event.target.value })}
              />
            </Field>
            <Field label="IVA (%)">
              <input
                className="input"
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={form.tax_rate}
                onChange={(event) => setForm({ ...form, tax_rate: event.target.value })}
              />
            </Field>
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <Modal
        open={Boolean(receiveLine)}
        title="Registrar recepción de la línea"
        subtitle={receiveLine?.description}
        onClose={() => setReceiveLine(null)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setReceiveLine(null)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="receive-line" className="btn btn-primary" disabled={busy || !receiveLocation}>
              {busy ? <span className="spinner" /> : <IconArrowIn />} Confirmar recepción
            </button>
          </>
        }
      >
        <form id="receive-line" className="stack" onSubmit={doReceive}>
          <div className="form-grid">
            <Field label="Cantidad recibida" required>
              <input
                className="input"
                type="number"
                min="0.001"
                step="0.001"
                value={receiveQty}
                onChange={(event) => setReceiveQty(event.target.value)}
                required
              />
            </Field>
            <Field label="Cantidad facturada">
              <input className="input" value={receiveLine ? fmtNumber(receiveLine.quantity, 3) : ""} readOnly />
            </Field>
          </div>
          <Field label="Ubicación de destino" required>
            <LocationPicker
              value={receiveLocation?.id ?? null}
              onChange={(location) =>
                setReceiveLocation(location ? { id: location.id, code: location.full_code } : null)
              }
            />
          </Field>
          <div className="alert">
            <span>
              Se crea un movimiento de recepción confirmado, vinculado a la línea de factura. La conciliación
              posterior comparará automáticamente esta cantidad con la facturada.
            </span>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={reconcileOpen}
        title="Conciliar factura"
        message={
          <>
            Se recalcularán las cantidades recibidas de cada línea a partir de los movimientos confirmados. Si
            alguna línea no coincide, la factura quedará marcada como <b>discrepancia</b> para revisión humana.
          </>
        }
        confirmLabel="Conciliar ahora"
        busy={busy}
        onConfirm={reconcile}
        onClose={() => setReconcileOpen(false)}
      />

      <ConfirmDialog
        open={Boolean(deleteLine)}
        title="Eliminar línea"
        message={
          <>
            Se eliminará la línea <b>#{deleteLine?.line_number}</b> sin recepciones asociadas. El documento
            original no se modifica.
          </>
        }
        confirmLabel="Eliminar"
        danger
        busy={busy}
        onConfirm={removeLine}
        onClose={() => setDeleteLine(null)}
      />
    </>
  );
}

export default function InvoicePage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <InvoiceDetail />
    </Suspense>
  );
}
