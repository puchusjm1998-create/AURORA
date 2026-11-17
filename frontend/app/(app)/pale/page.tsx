"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import {
  fmtDateTime,
  fmtNumber,
  fmtQty,
  movementBadge,
  movementLabel,
  palletStatusMeta,
  trackingLabel,
} from "@/lib/format";
import type { Movement, Page, Pallet, Product } from "@/lib/types";
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
  QrPreview,
  useToast,
  type BadgeTone,
} from "@/components/ui";
import {
  IconCheck,
  IconPallet,
  IconPrint,
  IconRefresh,
  IconTrash,
} from "@/components/icons";

interface PalletMovementRow {
  id: string;
  reference: string;
  type: string;
  status: string;
  product: string;
  quantity: string;
  created_at: string;
  reason: string;
}

function PalletDetail() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const { can } = useAuth();
  const toast = useToast();

  const pallet = useApi<Pallet>(id ? `/api/v1/pallets/${id}` : null, [id]);
  const movements = useApi<Page<PalletMovementRow>>(
    id ? withQuery(`/api/v1/pallets/${id}/movements`, { limit: 20 }) : null,
    [id],
  );

  const [addOpen, setAddOpen] = useState(false);
  const [product, setProduct] = useState<Product | null>(null);
  const [quantity, setQuantity] = useState("");
  const [batch, setBatch] = useState("");
  const [serials, setSerials] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sealOpen, setSealOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [destination, setDestination] = useState<{ id: string; code: string } | null>(null);
  const [shipOpen, setShipOpen] = useState(false);
  const [shipDoc, setShipDoc] = useState("");
  const [removeItem, setRemoveItem] = useState<{ id: string; name: string; quantity: string } | null>(null);
  const [removeDestination, setRemoveDestination] = useState<{ id: string; code: string } | null>(null);

  const data = pallet.data;

  async function addItem(event: React.FormEvent) {
    event.preventDefault();
    if (!data || !product) {
      setError("Seleccione un producto.");
      return;
    }
    setError(null);
    const serialList = serials
      .split(/[\n,;]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (product.tracking_mode === "unit" && serialList.length !== Number(quantity)) {
      setError(`Indique ${quantity} números de serie para las unidades.`);
      return;
    }
    setBusy(true);
    try {
      await api(`/api/v1/pallets/${data.id}/items`, {
        method: "POST",
        body: {
          product_id: product.id,
          quantity,
          batch_code: batch || null,
          unit_serials: product.tracking_mode === "unit" ? serialList : null,
        },
      });
      toast.success("Mercancía añadida", `${product.name} · ${quantity} ${product.uom}`);
      setAddOpen(false);
      setProduct(null);
      setQuantity("");
      setBatch("");
      setSerials("");
      pallet.reload();
      movements.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function action(path: string, body: unknown, success: string, method: "POST" | "DELETE" = "POST") {
    if (!data) return;
    setBusy(true);
    try {
      await api(path, { method, body });
      toast.success(success);
      setSealOpen(false);
      setMoveOpen(false);
      setShipOpen(false);
      setRemoveItem(null);
      pallet.reload();
      movements.reload();
    } catch (err) {
      toast.error("Operación rechazada", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!id) {
    return <EmptyState title="Palé no indicado" description="Selecciona un palé desde el listado o escanea su QR." action={<Link className="btn btn-primary btn-sm" href="/pales">Ir a palés</Link>} />;
  }
  if (pallet.error) return <ErrorBlock message={pallet.error} onRetry={pallet.reload} />;
  if (pallet.loading || !data) return <LoadingBlock label="Cargando palé…" />;

  const statusMeta = palletStatusMeta[data.status];
  const payload = `aurora://pallet/${data.code}`;
  const editable = data.status === "open";

  return (
    <>
      <PageHeader
        eyebrow="Ficha de palé"
        title={data.code}
        subtitle={`${data.item_count} referencias · ${fmtNumber(data.total_units, 3)} unidades · ${data.location_code ?? "sin ubicación"}`}
        actions={
          <>
            <Link href="/pales" className="btn btn-ghost">
              <IconPallet /> Palés
            </Link>
            <Link href={`/etiquetas?kind=pallet&ids=${data.id}`} className="btn btn-ghost">
              <IconPrint /> Etiqueta
            </Link>
            {can("pallets.write") && editable ? (
              <button type="button" className="btn btn-primary" onClick={() => setAddOpen(true)}>
                Añadir mercancía
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
                <span className="sku">{data.code}</span>
                <Badge tone={statusMeta.tone as "success"}>{statusMeta.label}</Badge>
                {data.location_code ? <span className="code-chip location">{data.location_code}</span> : null}
              </div>
              <h1>Palé {data.code.split("-").pop()}</h1>
              <div className="detail-meta" style={{ marginTop: 8 }}>
                <span>Almacén: <b>{data.warehouse_code}</b></span>
                <span>Creado: <b>{fmtDateTime(data.created_at)}</b></span>
                {data.sealed_at ? <span>Precintado: <b>{fmtDateTime(data.sealed_at)}</b></span> : null}
                {data.gross_weight_kg ? <span>Peso: <b>{fmtNumber(data.gross_weight_kg, 2)} kg</b></span> : null}
              </div>
            </div>
            <QrPreview payload={payload} code={data.code} />
          </div>
          {data.notes ? <p className="small text-soft">{data.notes}</p> : null}
          {can("pallets.write") ? (
            <div className="row" style={{ gap: 8 }}>
              {editable && data.items.length > 0 ? (
                <button type="button" className="btn btn-sm btn-success" onClick={() => setSealOpen(true)}>
                  <IconCheck /> Precintar palé
                </button>
              ) : null}
              {["open", "sealed"].includes(data.status) && data.location_code ? (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setMoveOpen(true)}>
                  Reubicar
                </button>
              ) : null}
              {["open", "sealed"].includes(data.status) ? (
                <button type="button" className="btn btn-sm btn-danger" onClick={() => setShipOpen(true)}>
                  Expedir palé
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="split">
          <div className="stack">
            <Card title="Contenido del palé" flush>
              {data.items.length === 0 ? (
                <EmptyState
                  icon={<IconPallet />}
                  title="Palé vacío"
                  description="Añade referencias para vincularlas a este palé y registrar su recepción."
                  action={
                    can("pallets.write") && editable ? (
                      <button type="button" className="btn btn-sm btn-primary" onClick={() => setAddOpen(true)}>
                        Añadir mercancía
                      </button>
                    ) : undefined
                  }
                />
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Producto</th>
                        <th>SKU</th>
                        <th>Lote</th>
                        <th className="num">Cantidad</th>
                        <th>Trazabilidad</th>
                        {editable && can("pallets.write") ? <th className="actions" /> : null}
                      </tr>
                    </thead>
                    <tbody>
                      {data.items.map((item) => (
                        <tr key={item.id}>
                          <td>
                            <Link href={`/producto?id=${item.product_id}`} className="strong small">
                              {item.product.name}
                            </Link>
                          </td>
                          <td className="mono small">{item.product.sku}</td>
                          <td className="mono small">{item.batch_code ?? "—"}</td>
                          <td className="num">{fmtQty(item.quantity, item.product.uom)}</td>
                          <td className="small text-muted">{trackingLabel[item.product.tracking_mode]}</td>
                          {editable && can("pallets.write") ? (
                            <td className="actions">
                              <button
                                type="button"
                                className="btn btn-sm btn-ghost"
                                aria-label={`Retirar ${item.product.name} del palé`}
                                onClick={() =>
                                  setRemoveItem({
                                    id: item.id,
                                    name: item.product.name,
                                    quantity: String(item.quantity),
                                  })
                                }
                              >
                                <IconTrash />
                              </button>
                            </td>
                          ) : null}
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={3}>Total</td>
                        <td className="num">{fmtNumber(data.total_units, 3)}</td>
                        <td colSpan={editable && can("pallets.write") ? 2 : 1} />
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </Card>

            <Card title="Historial del palé" flush>
              {movements.loading && !movements.data ? (
                <LoadingBlock />
              ) : !movements.data || movements.data.items.length === 0 ? (
                <EmptyState title="Sin movimientos" description="Todavía no se ha registrado actividad sobre este palé." />
              ) : (
                <div className="table-wrap">
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th>Referencia</th>
                        <th>Tipo</th>
                        <th>Producto</th>
                        <th className="num">Cantidad</th>
                        <th>Fecha</th>
                      </tr>
                    </thead>
                    <tbody>
                      {movements.data.items.map((movement) => (
                        <tr key={movement.id}>
                          <td className="mono">{movement.reference}</td>
                          <td>
                            <Badge tone={(movementBadge[movement.status as "confirmed"]?.tone ?? "neutral") as BadgeTone}>
                              {movementLabel(movement.type)}
                            </Badge>
                          </td>
                          <td className="small">{movement.product}</td>
                          <td className="num">{fmtQty(movement.quantity)}</td>
                          <td className="small text-muted nowrap">{fmtDateTime(movement.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>

          <div className="side-panel">
            <Card title="Resumen logístico">
              <dl className="def-list">
                <div className="def-row">
                  <dt>Estado</dt>
                  <dd><Badge tone={statusMeta.tone as "success"}>{statusMeta.label}</Badge></dd>
                </div>
                <div className="def-row">
                  <dt>Ubicación</dt>
                  <dd>
                    {data.location_code ? (
                      <Link href={`/ubicacion?code=${encodeURIComponent(data.location_code)}`} className="code-chip location">
                        {data.location_code}
                      </Link>
                    ) : (
                      "Sin asignar"
                    )}
                  </dd>
                </div>
                <div className="def-row">
                  <dt>Referencias</dt>
                  <dd>{data.item_count}</dd>
                </div>
                <div className="def-row">
                  <dt>Unidades</dt>
                  <dd>{fmtNumber(data.total_units, 3)}</dd>
                </div>
                <div className="def-row">
                  <dt>Peso bruto</dt>
                  <dd>{data.gross_weight_kg ? `${fmtNumber(data.gross_weight_kg, 2)} kg` : "—"}</dd>
                </div>
              </dl>
            </Card>
            <div className="alert">
              <strong>Código persistente</strong>
              <span>
                El código {data.code} no se reutilizará nunca. Aunque el palé se expida, su historial y su QR
                siguen siendo consultables.
              </span>
            </div>
          </div>
        </div>
      </div>

      <Modal
        open={addOpen}
        title="Añadir mercancía al palé"
        subtitle={`${data.code} · ${data.location_code ?? "sin ubicación"}`}
        onClose={() => setAddOpen(false)}
        wide
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setAddOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="add-item" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconCheck />} Registrar recepción
            </button>
          </>
        }
      >
        <form id="add-item" className="stack" onSubmit={addItem}>
          <Field label="Producto" required>
            <ProductPicker value={product?.id ?? null} onChange={setProduct} />
          </Field>
          <div className="form-grid">
            <Field label="Cantidad" required>
              <input
                className="input"
                type="number"
                min="0.001"
                step="0.001"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                required
              />
            </Field>
            <Field
              label="Lote"
              required={product?.tracking_mode === "batch"}
              hint="Obligatorio para productos con lote"
            >
              <input className="input mono" value={batch} onChange={(event) => setBatch(event.target.value)} />
            </Field>
          </div>
          {product?.tracking_mode === "unit" ? (
            <Field
              label="Números de serie"
              required
              hint={`Uno por línea; deben coincidir con la cantidad (${quantity || 0}).`}
            >
              <textarea
                className="textarea mono"
                value={serials}
                onChange={(event) => setSerials(event.target.value)}
                placeholder={"SN-001\nSN-002"}
              />
            </Field>
          ) : null}
          {error ? <div className="form-error">{error}</div> : null}
          <p className="hint">
            Al guardar se crea un movimiento de recepción confirmado en la ubicación del palé. La cantidad
            pasa a formar parte del stock físico.
          </p>
        </form>
      </Modal>

      <ConfirmDialog
        open={sealOpen}
        title="Precintar palé"
        message={
          <>
            El palé <b>{data.code}</b> quedará cerrado. No se podrán añadir ni retirar referencias, pero sí
            reubicarlo o expedirlo.
          </>
        }
        confirmLabel="Precintar"
        busy={busy}
        onConfirm={() => action(`/api/v1/pallets/${data.id}/seal`, {}, "Palé precintado")}
        onClose={() => setSealOpen(false)}
      />

      <Modal
        open={moveOpen}
        title="Reubicar palé"
        subtitle={`${data.code} · actualmente en ${data.location_code ?? "sin ubicación"}`}
        onClose={() => setMoveOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setMoveOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !destination}
              onClick={() =>
                action(
                  `/api/v1/pallets/${data.id}/move`,
                  { destination_location_id: destination?.id, reason: "Reubicación de palé" },
                  "Palé reubicado",
                )
              }
            >
              {busy ? <span className="spinner" /> : <IconCheck />} Confirmar reubicación
            </button>
          </>
        }
      >
        <Field label="Nueva ubicación" required hint="Se valida la capacidad de la ubicación destino.">
          <LocationPicker
            value={destination?.id ?? null}
            onChange={(location) =>
              setDestination(location ? { id: location.id, code: location.full_code } : null)
            }
          />
        </Field>
        <div className="alert" style={{ marginTop: 12 }}>
          <span>La reubicación genera un movimiento por cada referencia del palé, con confirmación física.</span>
        </div>
      </Modal>

      <Modal
        open={shipOpen}
        title="Expedir palé"
        subtitle={`${data.code} · ${data.item_count} referencias`}
        onClose={() => setShipOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setShipOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button
              type="button"
              className="btn btn-danger"
              disabled={busy}
              onClick={() =>
                action(
                  `/api/v1/pallets/${data.id}/ship`,
                  { document_ref: shipDoc, reason: "Expedición de palé" },
                  "Palé expedido",
                )
              }
            >
              {busy ? <span className="spinner" /> : null} Confirmar expedición
            </button>
          </>
        }
      >
        <Field label="Documento de salida" hint="Albarán, pedido o referencia de transporte">
          <input
            className="input"
            value={shipDoc}
            onChange={(event) => setShipDoc(event.target.value)}
            placeholder="ALB-2026-0042"
          />
        </Field>
        <div className="alert danger" style={{ marginTop: 12 }}>
          <strong>Salida definitiva</strong>
          <span>
            Se descuenta todo el stock del palé y queda marcado como expedido. No se puede deshacer; cualquier
            corrección requiere una devolución o un ajuste autorizado.
          </span>
        </div>
      </Modal>

      <Modal
        open={Boolean(removeItem)}
        title="Retirar mercancía del palé"
        subtitle={removeItem?.name}
        onClose={() => setRemoveItem(null)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setRemoveItem(null)} disabled={busy}>
              Cancelar
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !removeDestination}
              onClick={() =>
                action(
                  `/api/v1/pallets/${data.id}/items/${removeItem?.id}?destination_location_id=${
                    removeDestination?.id ?? ""
                  }`,
                  undefined,
                  "Mercancía retirada del palé",
                  "DELETE",
                )
              }
            >
              {busy ? <span className="spinner" /> : <IconCheck />} Retirar al almacén
            </button>
          </>
        }
      >
        <Field label="Ubicación de destino de la mercancía" required>
          <LocationPicker
            value={removeDestination?.id ?? null}
            onChange={(location) =>
              setRemoveDestination(location ? { id: location.id, code: location.full_code } : null)
            }
          />
        </Field>
        <p className="hint">
          La mercancía se transfiere al almacén mediante un movimiento interno; el stock no se pierde.
        </p>
      </Modal>
    </>
  );
}

export default function PalletPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <PalletDetail />
    </Suspense>
  );
}
