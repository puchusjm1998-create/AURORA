"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  fmtDateTime,
  fmtNumber,
  makeIdempotencyKey,
  movementBadge,
  movementLabel,
  trackingLabel,
} from "@/lib/format";
import type {
  Movement,
  MovementType,
  Page,
  Product,
  ProductWhereabouts,
} from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { LocationPicker, PalletPicker, ProductPicker } from "@/components/pickers";
import {
  Badge,
  Card,
  Field,
  LoadingBlock,
  PageHeader,
  Tabs,
  useToast,
} from "@/components/ui";
import {
  IconArrowIn,
  IconArrowOut,
  IconCheck,
  IconMovements,
  IconRefresh,
} from "@/components/icons";

type Tab = "recepcion" | "expedicion" | "transferencia" | "ajuste";

const TAB_TYPE: Record<Tab, MovementType> = {
  recepcion: "reception",
  expedicion: "shipment",
  transferencia: "internal_move",
  ajuste: "adjustment",
};

const TAB_META: Record<Tab, { title: string; description: string; button: string }> = {
  recepcion: {
    title: "Recepción de mercancía",
    description: "Incrementa el stock físico en la ubicación o palé de destino. Queda ligado a la factura si se indica.",
    button: "Confirmar recepción",
  },
  expedicion: {
    title: "Expedición / salida",
    description: "Descuenta stock disponible. Nunca permite dejar existencias negativas ni expedir mercancía reservada.",
    button: "Confirmar expedición",
  },
  transferencia: {
    title: "Movimiento interno",
    description: "Traslada stock entre ubicaciones o palés. El total del almacén se mantiene inalterado.",
    button: "Confirmar movimiento",
  },
  ajuste: {
    title: "Ajuste autorizado",
    description: "Corrige diferencias de inventario. Solo niveles 1 y 2, siempre con motivo documentado.",
    button: "Registrar ajuste",
  },
};

interface PositionOption {
  key: string;
  locationId: string;
  locationCode: string;
  palletId: string | null;
  palletCode: string | null;
  available: number;
}

function OperationsForm() {
  const search = useSearchParams();
  const { user, can } = useAuth();
  const toast = useToast();
  const initialTab = (search.get("tab") as Tab) || "recepcion";
  const [tab, setTab] = useState<Tab>(
    ["recepcion", "expedicion", "transferencia", "ajuste"].includes(initialTab) ? initialTab : "recepcion",
  );
  const prefillProduct = search.get("product");

  const [product, setProduct] = useState<Product | null>(null);
  const [quantity, setQuantity] = useState("");
  const [fromLocation, setFromLocation] = useState<{ id: string; code: string } | null>(null);
  const [fromPalletId, setFromPalletId] = useState<string | null>(null);
  const [fromPositionKey, setFromPositionKey] = useState("");
  const [toLocation, setToLocation] = useState<{ id: string; code: string } | null>(null);
  const [toPallet, setToPallet] = useState<{ id: string; code: string; locationId: string | null } | null>(null);
  const [batchCode, setBatchCode] = useState("");
  const [serials, setSerials] = useState("");
  const [reason, setReason] = useState("");
  const [documentRef, setDocumentRef] = useState("");
  const [physicalConfirmed, setPhysicalConfirmed] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(makeIdempotencyKey);
  const [lastMovement, setLastMovement] = useState<Movement | null>(null);

  const prefill = useApi<Product>(prefillProduct ? `/api/v1/products/${prefillProduct}` : null, [prefillProduct]);
  useEffect(() => {
    if (prefill.data && !product) setProduct(prefill.data);
  }, [prefill.data, product]);

  const whereabouts = useApi<ProductWhereabouts>(
    product ? `/api/v1/products/${product.id}/whereabouts` : null,
    [product?.id],
  );
  const recent = useApi<Page<Movement>>(withQuery("/api/v1/movements", { limit: 8 }), []);

  const positions: PositionOption[] = useMemo(() => {
    return (whereabouts.data?.positions ?? [])
      .filter((position) => Number(position.available_quantity) > 0)
      .map((position) => ({
        key: `${position.location_id}|${position.pallet_id ?? ""}`,
        locationId: position.location_id,
        locationCode: position.location_code,
        palletId: position.pallet_id,
        palletCode: position.pallet_code,
        available: Number(position.available_quantity),
      }));
  }, [whereabouts.data]);

  useEffect(() => {
    setFromPositionKey("");
    setFromLocation(null);
    setFromPalletId(null);
  }, [product?.id]);

  useEffect(() => {
    if (toPallet?.locationId) {
      setToLocation({ id: toPallet.locationId, code: toPallet.code });
    }
  }, [toPallet]);

  function resetForm(keepProduct = true) {
    setQuantity("");
    setBatchCode("");
    setSerials("");
    setReason("");
    setDocumentRef("");
    setFromLocation(null);
    setFromPalletId(null);
    setFromPositionKey("");
    setToLocation(null);
    setToPallet(null);
    setError(null);
    setIdempotencyKey(makeIdempotencyKey());
    if (!keepProduct) setProduct(null);
  }

  function switchTab(next: Tab) {
    setTab(next);
    setLastMovement(null);
    resetForm();
  }

  function onPositionChange(key: string) {
    setFromPositionKey(key);
    const position = positions.find((item) => item.key === key);
    if (!position) {
      setFromLocation(null);
      setFromPalletId(null);
      return;
    }
    setFromLocation({ id: position.locationId, code: position.locationCode });
    setFromPalletId(position.palletId);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!product) {
      setError("Seleccione un producto.");
      return;
    }
    const qty = Number(quantity.replace(",", "."));
    if (!Number.isFinite(qty) || qty === 0) {
      setError("Indique una cantidad distinta de cero.");
      return;
    }
    if (tab !== "recepcion" && tab !== "ajuste" && !fromLocation) {
      setError("Seleccione la ubicación de origen (o una posición con stock).");
      return;
    }
    if ((tab === "recepcion" || tab === "transferencia") && !toLocation) {
      setError("Seleccione la ubicación de destino.");
      return;
    }
    if (tab === "ajuste" && !reason.trim()) {
      setError("El ajuste requiere un motivo documentado.");
      return;
    }
    if (product.tracking_mode === "batch" && !batchCode.trim()) {
      setError("Este producto requiere indicar el lote.");
      return;
    }
    if (product.tracking_mode === "unit" && tab === "recepcion") {
      const list = serials
        .split(/[\n,;]+/)
        .map((value) => value.trim())
        .filter(Boolean);
      if (list.length !== Math.abs(qty)) {
        setError(`Indique exactamente ${Math.abs(qty)} números de serie (uno por línea).`);
        return;
      }
    }

    const payload: Record<string, unknown> = {
      movement_type: TAB_TYPE[tab],
      product_id: product.id,
      quantity: tab === "ajuste" ? qty : Math.abs(qty),
      reason: reason.trim(),
      document_ref: documentRef.trim(),
      batch_code: batchCode.trim() || null,
      worker_id: user?.employee?.id ?? null,
      confirm: true,
      physical_confirmed: physicalConfirmed,
      idempotency_key: idempotencyKey,
    };
    if (tab === "recepcion") {
      payload.to_location_id = toLocation?.id;
      payload.to_pallet_id = toPallet?.id ?? null;
      if (product.tracking_mode === "unit") {
        payload.unit_serials = serials
          .split(/[\n,;]+/)
          .map((value) => value.trim())
          .filter(Boolean);
      }
    }
    if (tab === "expedicion") {
      payload.from_location_id = fromLocation?.id;
      payload.from_pallet_id = fromPalletId;
    }
    if (tab === "transferencia") {
      payload.from_location_id = fromLocation?.id;
      payload.from_pallet_id = fromPalletId;
      payload.to_location_id = toLocation?.id;
      payload.to_pallet_id = toPallet?.id ?? null;
    }
    if (tab === "ajuste") {
      if (qty > 0) payload.to_location_id = toLocation?.id ?? fromLocation?.id;
      else payload.from_location_id = fromLocation?.id ?? toLocation?.id;
    }

    setBusy(true);
    try {
      const movement = await api<Movement>("/api/v1/movements", { method: "POST", body: payload });
      setLastMovement(movement);
      toast.success(
        `${movementLabel(movement.movement_type)} confirmada`,
        `${movement.reference} · ${fmtNumber(movement.quantity, 3)} ${movement.uom}`,
      );
      resetForm();
      whereabouts.reload();
      recent.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!can("movements.write")) {
    return (
      <div className="alert warning">
        <strong>Permiso insuficiente</strong>
        <span>Su nivel de acceso permite consultar, pero no registrar movimientos de stock.</span>
      </div>
    );
  }

  const needsSource = tab === "expedicion" || tab === "transferencia";
  const needsTarget = tab === "recepcion" || tab === "transferencia";
  const meta = TAB_META[tab];
  const isAdjustment = tab === "ajuste";
  const canAdjust = Boolean(user && user.role_level <= 2);

  return (
    <>
      <PageHeader
        eyebrow="Operaciones de almacén"
        title="Registrar movimiento"
        subtitle="Toda operación se valida en el servidor, se aplica en una transacción y queda auditada."
        actions={
          <Link href="/movimientos" className="btn btn-ghost">
            <IconMovements /> Historial completo
          </Link>
        }
      />

      <div className="split">
        <div className="stack">
          <section className="card">
            <Tabs
              tabs={[
                { value: "recepcion", label: "Recepción" },
                { value: "expedicion", label: "Expedición" },
                { value: "transferencia", label: "Transferencia" },
                ...(canAdjust ? [{ value: "ajuste" as Tab, label: "Ajuste" }] : []),
              ]}
              value={tab}
              onChange={switchTab}
            />
            <div className="card-body">
              <div className="row" style={{ marginBottom: 18, gap: 8 }}>
                {tab === "recepcion" ? <IconArrowIn /> : tab === "expedicion" ? <IconArrowOut /> : <IconMovements />}
                <div>
                  <div className="strong">{meta.title}</div>
                  <div className="small text-muted">{meta.description}</div>
                </div>
              </div>

              <form onSubmit={submit} className="form-grid">
                <Field label="Producto" required className="full">
                  <ProductPicker value={product?.id ?? null} onChange={setProduct} />
                  {product ? (
                    <span className="hint">
                      {product.sku} · {trackingLabel[product.tracking_mode]} · disponible{" "}
                      {fmtNumber(whereabouts.data?.stock.available ?? product.stock.available, 3)} {product.uom}
                    </span>
                  ) : null}
                </Field>

                {needsSource ? (
                  <Field
                    label="Posición de origen"
                    required
                    className="full"
                    hint={
                      product
                        ? "Solo se muestran posiciones con stock disponible (físico menos reservado)."
                        : "Selecciona primero un producto."
                    }
                  >
                    <select
                      className="select"
                      value={fromPositionKey}
                      onChange={(event) => onPositionChange(event.target.value)}
                      disabled={!product}
                    >
                      <option value="">
                        {product
                          ? positions.length
                            ? "Seleccione ubicación / palé con stock…"
                            : "Sin stock disponible para este producto"
                          : "Seleccione un producto…"}
                      </option>
                      {positions.map((position) => (
                        <option key={position.key} value={position.key}>
                          {position.locationCode}
                          {position.palletCode ? ` · ${position.palletCode}` : " · estantería"} — disponible{" "}
                          {fmtNumber(position.available, 3)}
                        </option>
                      ))}
                    </select>
                    {fromLocation ? (
                      <span className="hint">
                        Origen: <span className="code-chip location">{fromLocation.code}</span>
                        {fromPalletId ? " · palé seleccionado" : ""}
                      </span>
                    ) : null}
                  </Field>
                ) : null}

                {tab === "ajuste" ? (
                  <Field
                    label="Ubicación del ajuste"
                    required
                    className="full"
                    hint="Para ajustes negativos se descuenta de esta ubicación; para positivos se suma."
                  >
                    <LocationPicker
                      value={toLocation?.id ?? fromLocation?.id ?? null}
                      onChange={(location) => {
                        setToLocation(location ? { id: location.id, code: location.full_code } : null);
                        setFromLocation(location ? { id: location.id, code: location.full_code } : null);
                      }}
                    />
                  </Field>
                ) : null}

                {needsTarget ? (
                  <>
                    <Field label="Ubicación de destino" required className="full">
                      <LocationPicker
                        value={toLocation?.id ?? null}
                        onChange={(location) =>
                          setToLocation(location ? { id: location.id, code: location.full_code } : null)
                        }
                      />
                    </Field>
                    <Field
                      label="Palé de destino (opcional)"
                      className="full"
                      hint="Solo palés abiertos. Al elegir palé, la ubicación se ajusta automáticamente."
                    >
                      <PalletPicker
                        value={toPallet?.id ?? null}
                        status="open"
                        onChange={(pallet) =>
                          setToPallet(
                            pallet
                              ? { id: pallet.id, code: pallet.code, locationId: pallet.location_id }
                              : null,
                          )
                        }
                      />
                    </Field>
                  </>
                ) : null}

                <Field
                  label="Cantidad"
                  required
                  hint={isAdjustment ? "Use signo negativo para reducir existencias" : "En unidades de medida del producto"}
                >
                  <input
                    className="input input-lg"
                    type="number"
                    step="0.001"
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                    placeholder="0"
                    required
                  />
                </Field>

                <Field
                  label="Lote / batch"
                  required={product?.tracking_mode === "batch"}
                  hint={product?.tracking_mode === "batch" ? "Obligatorio para este producto" : "Opcional"}
                >
                  <input
                    className="input mono"
                    value={batchCode}
                    onChange={(event) => setBatchCode(event.target.value)}
                    placeholder="Ej. LOTE-2026-A"
                  />
                </Field>

                {product?.tracking_mode === "unit" && tab === "recepcion" ? (
                  <Field
                    label="Números de serie"
                    required
                    className="full"
                    hint={`Uno por línea. Deben ser exactamente ${quantity || "N"} unidades; cada una recibe un código AUR-OBJ.`}
                  >
                    <textarea
                      className="textarea mono"
                      value={serials}
                      onChange={(event) => setSerials(event.target.value)}
                      placeholder={"SN-0001\nSN-0002"}
                    />
                  </Field>
                ) : null}

                <Field label="Motivo" required={isAdjustment} className={isAdjustment ? "full" : ""}>
                  <input
                    className="input"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder={isAdjustment ? "Obligatorio para ajustes" : "Opcional (ej. pedido cliente)"}
                  />
                </Field>

                <Field label="Documento asociado" hint="Albarán, pedido o factura">
                  <input
                    className="input"
                    value={documentRef}
                    onChange={(event) => setDocumentRef(event.target.value)}
                    placeholder="ALB-2026-0012"
                  />
                </Field>

                <div className="full">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={physicalConfirmed}
                      onChange={(event) => setPhysicalConfirmed(event.target.checked)}
                    />
                    Confirmo la verificación física de la mercancía en la ubicación indicada.
                  </label>
                </div>

                {error ? <div className="form-error full">{error}</div> : null}

                <div className="full row" style={{ justifyContent: "flex-end", marginTop: 4 }}>
                  <button type="submit" className="btn btn-primary btn-lg" disabled={busy}>
                    {busy ? <span className="spinner" /> : <IconCheck />}
                    {busy ? "Aplicando…" : meta.button}
                  </button>
                </div>
              </form>
            </div>
          </section>

          {lastMovement ? (
            <div className="form-ok">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  Movimiento <b>{lastMovement.reference}</b> confirmado correctamente.
                </span>
                <Link href={`/movimientos?search=${lastMovement.reference}`} className="btn btn-sm btn-ghost">
                  Ver en historial
                </Link>
              </div>
            </div>
          ) : null}
        </div>

        <div className="side-panel">
          <Card title="Últimos movimientos" subtitle="Actividad reciente del almacén" flush>
            {recent.loading && !recent.data ? (
              <LoadingBlock label="Cargando…" />
            ) : (
              <div className="stack" style={{ gap: 0 }}>
                {(recent.data?.items ?? []).map((movement) => {
                  const status = movementBadge[movement.status];
                  return (
                    <div
                      key={movement.id}
                      className="row"
                      style={{
                        justifyContent: "space-between",
                        padding: "11px 16px",
                        borderBottom: "1px solid var(--border)",
                        gap: 10,
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div className="small mono text-accent">{movement.reference}</div>
                        <div className="small truncate">{movement.product_name}</div>
                        <div className="tiny text-muted">
                          {movementLabel(movement.movement_type)} · {fmtDateTime(movement.created_at)}
                        </div>
                      </div>
                      <div style={{ textAlign: "right", flex: "none" }}>
                        <div className="small strong">{fmtNumber(movement.quantity, 3)}</div>
                        <Badge tone={status.tone as "success"}>{status.label}</Badge>
                      </div>
                    </div>
                  );
                })}
                {recent.data && recent.data.items.length === 0 ? (
                  <div className="empty" style={{ padding: 24 }}>
                    <IconRefresh />
                    <strong>Sin movimientos aún</strong>
                    <span className="small">Registra la primera operación para verla aquí.</span>
                  </div>
                ) : null}
              </div>
            )}
          </Card>

          {product && whereabouts.data ? (
            <Card title="Stock disponible" subtitle="Posiciones válidas como origen">
              {positions.length === 0 ? (
                <p className="small text-muted">No hay stock disponible de esta referencia.</p>
              ) : (
                <div className="stack" style={{ gap: 10 }}>
                  {positions.slice(0, 6).map((position) => (
                    <div key={position.key} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                      <span className="code-chip location">{position.locationCode}</span>
                      <span className="small">
                        {position.palletCode ? <span className="mono tiny">{position.palletCode}</span> : null}{" "}
                        <b>{fmtNumber(position.available, 3)}</b> {product.uom}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ) : null}

          <div className="alert">
            <strong>Confirmación humana</strong>
            <span>
              Ninguna operación se ejecuta sin confirmación física del trabajador. El sistema rechaza
              cantidades negativas, duplicados y movimientos sobre stock reservado.
            </span>
          </div>
        </div>
      </div>
    </>
  );
}

export default function OperationsPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <OperationsForm />
    </Suspense>
  );
}
