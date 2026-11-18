"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import {
  fmtDateTime,
  fmtMoney,
  fmtNumber,
  fmtQty,
  movementBadge,
  movementLabel,
  trackingLabel,
  unitStatusMeta,
} from "@/lib/format";
import type {
  Page,
  Product,
  ProductUnit,
  ProductWhereabouts,
  Movement,
} from "@/lib/types";
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
  Stat,
  useToast,
} from "@/components/ui";
import {
  IconArrowIn,
  IconArrowOut,
  IconBox,
  IconMovements,
  IconPin,
  IconPrint,
  IconQr,
  IconRefresh,
} from "@/components/icons";

interface SupplierOption {
  id: string;
  name: string;
}

function ProductDetail() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const { can, user } = useAuth();
  const toast = useToast();

  const whereabouts = useApi<ProductWhereabouts>(id ? `/api/v1/products/${id}/whereabouts` : null, [id]);
  const movements = useApi<Page<Movement>>(
    id ? withQuery("/api/v1/movements", { product_id: id, limit: 12 }) : null,
    [id],
  );
  const units = useApi<Page<ProductUnit>>(
    id ? withQuery(`/api/v1/products/${id}/units`, { limit: 100 }) : null,
    [id],
  );
  const suppliers = useApi<Page<SupplierOption>>(
    can("inventory.write") ? "/api/v1/suppliers?limit=200" : null,
  );

  const product = whereabouts.data?.product ?? null;
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    category: "",
    manufacturer_ref: "",
    barcode: "",
    supplier_id: "",
    uom: "",
    purchase_price: "0",
    unit_price: "0",
    min_stock: "0",
  });

  useEffect(() => {
    if (!product || !editing) return;
    setForm({
      name: product.name,
      description: product.description,
      category: product.category,
      manufacturer_ref: product.manufacturer_ref ?? "",
      barcode: product.barcode ?? "",
      supplier_id: product.supplier_id ?? "",
      uom: product.uom,
      purchase_price: String(product.purchase_price),
      unit_price: String(product.unit_price),
      min_stock: String(product.min_stock),
    });
  }, [product, editing]);

  if (!id) {
    return (
      <EmptyState
        title="Producto no indicado"
        description="Abra el producto desde el inventario o escanee su etiqueta QR."
        action={
          <Link href="/inventario" className="btn btn-primary btn-sm">
            Ir al inventario
          </Link>
        }
      />
    );
  }

  if (whereabouts.error) {
    return <ErrorBlock message={whereabouts.error} onRetry={whereabouts.reload} />;
  }
  if (whereabouts.loading || !product) {
    return <LoadingBlock label="Cargando ficha del producto…" />;
  }

  const stock = whereabouts.data!.stock;
  const payload = `aurora://product/${product.sku}`;
  const canAdjust = Boolean(user && user.role_level <= 2);

  async function save() {
    if (!product) return;
    setSaving(true);
    try {
      await api(`/api/v1/products/${product.id}`, {
        method: "PATCH",
        body: {
          name: form.name,
          description: form.description,
          category: form.category,
          manufacturer_ref: form.manufacturer_ref || null,
          barcode: form.barcode || null,
          supplier_id: form.supplier_id || null,
          uom: form.uom,
          purchase_price: form.purchase_price,
          unit_price: form.unit_price,
          min_stock: form.min_stock,
        },
      });
      toast.success("Producto actualizado");
      setEditing(false);
      whereabouts.reload();
    } catch (err) {
      toast.error("No se pudo guardar", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function deactivate() {
    if (!product) return;
    setDeleting(true);
    try {
      await api(`/api/v1/products/${product.id}`, { method: "DELETE" });
      toast.success("Producto desactivado", "El histórico se conserva íntegro.");
      setConfirmDeactivate(false);
      whereabouts.reload();
    } catch (err) {
      toast.error("No se pudo desactivar", errorMessage(err));
      setConfirmDeactivate(false);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Ficha de producto"
        title={product.name}
        subtitle={`SKU ${product.sku} · ${product.category} · seguimiento por ${trackingLabel[
          product.tracking_mode
        ].toLowerCase()}`}
        actions={
          <>
            <Link href="/inventario" className="btn btn-ghost">
              <IconBox /> Inventario
            </Link>
            <Link href={`/etiquetas?kind=product&ids=${product.id}`} className="btn btn-ghost">
              <IconPrint /> Etiqueta QR
            </Link>
            {can("inventory.write") ? (
              <button type="button" className="btn btn-ghost" onClick={() => setEditing(true)}>
                Editar
              </button>
            ) : null}
            {can("movements.write") ? (
              <Link
                href={`/operaciones?tab=recepcion&product=${product.id}`}
                className="btn btn-primary"
              >
                <IconArrowIn /> Registrar entrada
              </Link>
            ) : null}
          </>
        }
      />

      <div className="grid" style={{ gap: 18 }}>
        <div className="detail-hero">
          <div className="title-row">
            <div style={{ flex: 1, minWidth: 240 }}>
              <div className="row" style={{ gap: 8, marginBottom: 6 }}>
                <span className="sku">{product.sku}</span>
                {product.is_active ? <Badge tone="success">Activo</Badge> : <Badge tone="danger">Inactivo</Badge>}
                <Badge tone="accent" dot={false}>
                  {trackingLabel[product.tracking_mode]}
                </Badge>
              </div>
              <h1>{product.name}</h1>
              <div className="detail-meta" style={{ marginTop: 8 }}>
                <span>
                  Proveedor: <b>{product.supplier?.name ?? "—"}</b>
                </span>
                <span>
                  Ref. fabricante: <b>{product.manufacturer_ref ?? "—"}</b>
                </span>
                <span>
                  Unidad: <b>{product.uom}</b>
                </span>
                <span>
                  Stock mínimo: <b>{fmtNumber(product.min_stock, 0)}</b>
                </span>
              </div>
            </div>
            <QrPreview payload={payload} code={product.sku} />
          </div>
          {product.description ? <p className="small text-soft">{product.description}</p> : null}
          <div className="row" style={{ gap: 8 }}>
            {can("movements.write") ? (
              <>
                <Link
                  href={`/operaciones?tab=expedicion&product=${product.id}`}
                  className="btn btn-sm btn-ghost"
                >
                  <IconArrowOut /> Expedición
                </Link>
                <Link
                  href={`/operaciones?tab=transferencia&product=${product.id}`}
                  className="btn btn-sm btn-ghost"
                >
                  <IconMovements /> Transferencia
                </Link>
                {canAdjust ? (
                  <Link
                    href={`/operaciones?tab=ajuste&product=${product.id}`}
                    className="btn btn-sm btn-ghost"
                  >
                    Ajuste
                  </Link>
                ) : null}
              </>
            ) : null}
            {can("inventory.delete") ? (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => setConfirmDeactivate(true)}
                disabled={!product.is_active}
              >
                Desactivar
              </button>
            ) : null}
          </div>
        </div>

        <div className="grid grid-4">
          <Stat label="Físico" value={fmtNumber(stock.on_hand, 3)} meta={<span>{product.uom}</span>} accent />
          <Stat label="Reservado" value={fmtNumber(stock.reserved, 3)} meta={<span>comprometido</span>} />
          <Stat
            label="Disponible"
            value={fmtNumber(stock.available, 3)}
            meta={
              <Badge tone={Number(stock.available) > 0 ? "success" : "danger"}>
                {Number(stock.available) > 0 ? "Operativo" : "Sin disponible"}
              </Badge>
            }
          />
          <Stat
            label="Valor en stock"
            value={fmtMoney(stock.value)}
            meta={<span>{fmtMoney(product.purchase_price)} / {product.uom} compra</span>}
          />
        </div>

        <div className="split">
          <div className="stack">
            <Card
              title="Localización exacta"
              subtitle="Cada fila indica almacén, ubicación y palé donde se encuentra la mercancía"
              flush
              actions={<Badge tone="accent">{whereabouts.data!.positions.length} posiciones</Badge>}
            >
              {whereabouts.data!.positions.length === 0 ? (
                <EmptyState
                  icon={<IconPin />}
                  title="Sin existencias ubicadas"
                  description="Este producto no tiene stock en ninguna ubicación. Registra una recepción para ubicarlo."
                  action={
                    can("movements.write") ? (
                      <Link
                        href={`/operaciones?tab=recepcion&product=${product.id}`}
                        className="btn btn-sm btn-primary"
                      >
                        <IconArrowIn /> Registrar entrada
                      </Link>
                    ) : undefined
                  }
                />
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Ubicación</th>
                        <th>Palé</th>
                        <th className="num">Físico</th>
                        <th className="num">Reservado</th>
                        <th className="num">Disponible</th>
                        <th>Actualizado</th>
                        <th className="actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {whereabouts.data!.positions.map((position) => (
                        <tr key={position.id}>
                          <td>
                            <div className="row tight">
                              <span className="code-chip location">{position.location_code}</span>
                            </div>
                            <div className="tiny text-muted">
                              {position.warehouse_code} · {position.aisle}/{position.rack}/{position.level}/
                              {position.position}
                            </div>
                          </td>
                          <td>
                            {position.pallet_code ? (
                              <Link
                                href={`/pale?id=${position.pallet_id}`}
                                className="code-chip"
                              >
                                {position.pallet_code}
                              </Link>
                            ) : (
                              <span className="text-muted small">Estantería</span>
                            )}
                          </td>
                          <td className="num">{fmtNumber(position.quantity, 3)}</td>
                          <td className="num text-muted">{fmtNumber(position.reserved_quantity, 3)}</td>
                          <td className="num">{fmtNumber(position.available_quantity, 3)}</td>
                          <td className="small text-muted nowrap">{fmtDateTime(position.updated_at)}</td>
                          <td className="actions">
                            <Link
                              href={`/ubicacion?code=${encodeURIComponent(position.location_code)}`}
                              className="btn btn-sm btn-ghost"
                            >
                              Ubicación
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            {product.tracking_mode === "unit" ? (
              <Card
                title="Unidades individuales"
                subtitle="Cada objeto tiene un código QR persistente y no reutilizable"
                flush
                actions={<Badge tone="accent">{units.data?.total ?? 0} unidades</Badge>}
              >
                {units.loading && !units.data ? (
                  <LoadingBlock label="Cargando unidades…" />
                ) : !units.data || units.data.items.length === 0 ? (
                  <EmptyState title="Sin unidades registradas" description="Las unidades se crean automáticamente al recibir el producto." />
                ) : (
                  <div className="table-wrap">
                    <table className="table compact">
                      <thead>
                        <tr>
                          <th>Código</th>
                          <th>Serie</th>
                          <th>Estado</th>
                          <th>Ubicación</th>
                          <th>Palé</th>
                          <th className="actions">QR</th>
                        </tr>
                      </thead>
                      <tbody>
                        {units.data.items.map((unit) => {
                          const meta = unitStatusMeta[unit.status] ?? { tone: "neutral", label: unit.status };
                          return (
                            <tr key={unit.id}>
                              <td className="mono text-accent">{unit.code}</td>
                              <td className="small">{unit.serial_number ?? "—"}</td>
                              <td>
                                <Badge tone={meta.tone as "success"}>{meta.label}</Badge>
                              </td>
                              <td className="mono small">{unit.location_code ?? "—"}</td>
                              <td className="mono small">{unit.pallet_code ?? "—"}</td>
                              <td className="actions">
                                <Link href={`/etiquetas?kind=unit&ids=${unit.id}`} className="btn btn-sm btn-ghost">
                                  <IconQr />
                                </Link>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            ) : null}

            <Card
              title="Historial de movimientos"
              subtitle="Libro inmutable de entradas, salidas y transferencias"
              flush
              actions={
                <Link href={`/movimientos?product=${product.id}`} className="btn btn-sm btn-ghost">
                  Ver todo
                </Link>
              }
            >
              {movements.loading && !movements.data ? (
                <LoadingBlock label="Cargando movimientos…" />
              ) : !movements.data || movements.data.items.length === 0 ? (
                <EmptyState title="Sin movimientos" description="Aún no hay operaciones registradas para esta referencia." />
              ) : (
                <div className="table-wrap">
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th>Referencia</th>
                        <th>Tipo</th>
                        <th className="num">Cantidad</th>
                        <th>Origen → destino</th>
                        <th>Fecha</th>
                      </tr>
                    </thead>
                    <tbody>
                      {movements.data.items.map((movement) => {
                        const status = movementBadge[movement.status];
                        return (
                          <tr key={movement.id}>
                            <td className="mono">{movement.reference}</td>
                            <td>
                              <Badge tone={status.tone as "success"}>{movementLabel(movement.movement_type)}</Badge>
                            </td>
                            <td className="num">{fmtQty(movement.quantity, movement.uom)}</td>
                            <td className="mono small text-muted">
                              {movement.from_location_code ?? "—"} → {movement.to_location_code ?? "—"}
                            </td>
                            <td className="small text-muted nowrap">{fmtDateTime(movement.created_at)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>

          <div className="side-panel">
            <Card title="Datos maestros">
              <dl className="def-list">
                <div className="def-row">
                  <dt>Categoría</dt>
                  <dd>{product.category}</dd>
                </div>
                <div className="def-row">
                  <dt>Referencia</dt>
                  <dd>{product.manufacturer_ref ?? "—"}</dd>
                </div>
                <div className="def-row">
                  <dt>Código de barras</dt>
                  <dd className="mono">{product.barcode ?? "—"}</dd>
                </div>
                <div className="def-row">
                  <dt>Precio compra</dt>
                  <dd>{fmtMoney(product.purchase_price)}</dd>
                </div>
                <div className="def-row">
                  <dt>Precio venta</dt>
                  <dd>{fmtMoney(product.unit_price)}</dd>
                </div>
                <div className="def-row">
                  <dt>Seguimiento</dt>
                  <dd>{trackingLabel[product.tracking_mode]}</dd>
                </div>
                <div className="def-row">
                  <dt>Ubicaciones</dt>
                  <dd>{stock.locations}</dd>
                </div>
                {product.tracking_mode === "unit" ? (
                  <div className="def-row">
                    <dt>Unidades en stock</dt>
                    <dd>{stock.unit_count}</dd>
                  </div>
                ) : null}
                <div className="def-row">
                  <dt>En tránsito</dt>
                  <dd>{fmtNumber(stock.in_transit, 3)}</dd>
                </div>
                <div className="def-row">
                  <dt>Creado</dt>
                  <dd>{fmtDateTime(product.created_at)}</dd>
                </div>
              </dl>
            </Card>

            <Card title="Trazabilidad">
              <p className="small text-muted" style={{ marginBottom: 12 }}>
                Este QR identifica la referencia de forma unívoca. Imprímelo para la estantería o la ficha
                física del producto.
              </p>
              <div className="stack" style={{ gap: 8 }}>
                <Link href={`/etiquetas?kind=product&ids=${product.id}`} className="btn btn-block">
                  <IconPrint /> Imprimir etiqueta
                </Link>
                {whereabouts.data!.positions.length ? (
                  <Link
                    href={`/etiquetas?kind=location&ids=${encodeURIComponent(
                      whereabouts.data!.positions.map((position) => position.location_code).join(","),
                    )}`}
                    className="btn btn-ghost btn-block"
                  >
                    <IconQr /> Etiquetas de ubicación
                  </Link>
                ) : null}
              </div>
            </Card>
          </div>
        </div>
      </div>

      <Modal
        open={editing}
        title="Editar producto"
        subtitle="Los datos maestros quedan registrados en la auditoría."
        onClose={() => setEditing(false)}
        wide
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setEditing(false)} disabled={saving}>
              Cancelar
            </button>
            <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
              {saving ? <span className="spinner" /> : null} Guardar cambios
            </button>
          </>
        }
      >
        <div className="form-grid">
          <Field label="Nombre" required className="full">
            <input
              className="input"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </Field>
          <Field label="Categoría">
            <input
              className="input"
              value={form.category}
              onChange={(event) => setForm({ ...form, category: event.target.value })}
            />
          </Field>
          <Field label="Unidad de medida">
            <input
              className="input"
              value={form.uom}
              onChange={(event) => setForm({ ...form, uom: event.target.value })}
            />
          </Field>
          <Field label="Referencia del fabricante">
            <input
              className="input"
              value={form.manufacturer_ref}
              onChange={(event) => setForm({ ...form, manufacturer_ref: event.target.value })}
            />
          </Field>
          <Field label="Código de barras">
            <input
              className="input"
              value={form.barcode}
              onChange={(event) => setForm({ ...form, barcode: event.target.value })}
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
          <Field label="Precio de compra (€)" hint="Valoración de existencias">
            <input
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={form.purchase_price}
              onChange={(event) => setForm({ ...form, purchase_price: event.target.value })}
            />
          </Field>
          <Field label="Precio de venta (€)">
            <input
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={form.unit_price}
              onChange={(event) => setForm({ ...form, unit_price: event.target.value })}
            />
          </Field>
          <Field label="Stock mínimo" hint="Genera avisos de reposición">
            <input
              className="input"
              type="number"
              step="0.001"
              min="0"
              value={form.min_stock}
              onChange={(event) => setForm({ ...form, min_stock: event.target.value })}
            />
          </Field>
          <Field label="Descripción" className="full">
            <textarea
              className="textarea"
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmDeactivate}
        title="Desactivar producto"
        message={
          <>
            El producto <b>{product.sku}</b> dejará de estar disponible para nuevas operaciones. No se borra
            ningún movimiento ni histórico. Solo es posible si no tiene existencias.
          </>
        }
        confirmLabel="Desactivar"
        danger
        busy={deleting}
        onConfirm={deactivate}
        onClose={() => setConfirmDeactivate(false)}
      />
    </>
  );
}

export default function ProductPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <ProductDetail />
    </Suspense>
  );
}
