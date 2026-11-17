"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import {
  fmtDateTime,
  fmtNumber,
  fmtQty,
  reservationStatusMeta,
} from "@/lib/format";
import type { Page, Product, ProductWhereabouts, Reservation } from "@/lib/types";
import { ProductPicker } from "@/components/pickers";
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
  Pagination,
  SearchInput,
  Stat,
  useToast,
} from "@/components/ui";
import { IconPlus, IconRefresh, IconReserve } from "@/components/icons";

const LIMIT = 25;

export default function ReservationsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [status, setStatus] = useState("active");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(false);
  const [product, setProduct] = useState<Product | null>(null);
  const [positionKey, setPositionKey] = useState("");
  const [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [releaseTarget, setReleaseTarget] = useState<Reservation | null>(null);
  const debounced = useDebounced(search, 280);

  const query = useMemo(
    () =>
      withQuery("/api/v1/reservations", {
        status: status || null,
        reference: debounced || null,
        limit: LIMIT,
        offset,
      }),
    [status, debounced, offset],
  );
  const reservations = useApi<Page<Reservation>>(query);
  const activeCount = useApi<Page<Reservation>>("/api/v1/reservations?status=active&limit=1");
  const releasedCount = useApi<Page<Reservation>>("/api/v1/reservations?status=released&limit=1");
  const consumedCount = useApi<Page<Reservation>>("/api/v1/reservations?status=consumed&limit=1");
  const whereabouts = useApi<ProductWhereabouts>(
    open && product ? `/api/v1/products/${product.id}/whereabouts` : null,
    [open, product?.id],
  );

  const positions = useMemo(
    () =>
      (whereabouts.data && whereabouts.data.product.id === product?.id
        ? whereabouts.data.positions
        : [])
        .filter((position) => Number(position.available_quantity) > 0)
        .map((position) => ({
          key: `${position.location_id}|${position.pallet_id ?? ""}`,
          locationId: position.location_id,
          locationCode: position.location_code,
          palletId: position.pallet_id,
          palletCode: position.pallet_code,
          available: Number(position.available_quantity),
        })),
    [whereabouts.data, product?.id],
  );
  const selected = positions.find((position) => position.key === positionKey) ?? null;

  useEffect(() => {
    setPositionKey("");
    setQuantity("");
  }, [product?.id]);

  function openCreate() {
    setProduct(null);
    setPositionKey("");
    setQuantity("");
    setReference("");
    setExpiresAt("");
    setError(null);
    setOpen(true);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!product || !selected) {
      setError("Seleccione un producto y una posición con stock disponible.");
      return;
    }
    const qty = Number(quantity.replace(",", "."));
    if (!Number.isFinite(qty) || qty <= 0) {
      setError("Indique una cantidad mayor que cero.");
      return;
    }
    if (qty > selected.available) {
      setError(`Solo hay ${fmtNumber(selected.available, 3)} disponibles en esa posición.`);
      return;
    }
    if (expiresAt && new Date(expiresAt).getTime() <= Date.now()) {
      setError("La caducidad debe ser una fecha futura.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api<Reservation>("/api/v1/reservations", {
        method: "POST",
        body: {
          product_id: product.id,
          location_id: selected.locationId,
          pallet_id: selected.palletId,
          quantity,
          reference: reference.trim(),
          expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        },
      });
      toast.success("Reserva creada", `${reference.trim()} · ${fmtNumber(qty, 3)} ${product.uom}`);
      setOpen(false);
      reservations.reload();
      activeCount.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function release() {
    if (!releaseTarget) return;
    setBusy(true);
    try {
      await api(`/api/v1/reservations/${releaseTarget.id}/release`, { method: "POST" });
      toast.success("Reserva liberada", `${releaseTarget.reference} · stock disponible de nuevo`);
      setReleaseTarget(null);
      reservations.reload();
      activeCount.reload();
      releasedCount.reload();
    } catch (err) {
      toast.error("No se pudo liberar", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Preparación"
        title="Reservas de stock"
        subtitle="Compromete unidades para un pedido sin sacarlas del almacén. El stock reservado deja de estar disponible para otras salidas."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={reservations.reload} disabled={reservations.loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("reservations.write") ? (
              <button type="button" className="btn btn-primary" onClick={openCreate}>
                <IconPlus /> Nueva reserva
              </button>
            ) : null}
          </>
        }
      />

      <div className="grid grid-3" style={{ marginBottom: 18 }}>
        <Stat
          label="Reservas activas"
          value={activeCount.data?.total ?? "—"}
          meta={<span>unidades comprometidas</span>}
          accent
        />
        <Stat
          label="Liberadas"
          value={releasedCount.data?.total ?? "—"}
          meta={<span>stock devuelto a disponible</span>}
        />
        <Stat
          label="Consumidas"
          value={consumedCount.data?.total ?? "—"}
          meta={<span>salidas ya ejecutadas</span>}
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
            placeholder="Buscar por referencia de pedido…"
          />
          <select
            className="select"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            aria-label="Estado de la reserva"
          >
            <option value="active">Activas</option>
            <option value="">Todas</option>
            <option value="released">Liberadas</option>
            <option value="consumed">Consumidas</option>
            <option value="expired">Caducadas</option>
          </select>
          <span className="spacer" />
          <span className="count-chip">{reservations.data ? `${reservations.data.total} reservas` : "—"}</span>
        </div>

        {reservations.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={reservations.error} onRetry={reservations.reload} />
          </div>
        ) : null}
        {reservations.loading && !reservations.data ? <LoadingBlock label="Cargando reservas…" /> : null}
        {reservations.data && reservations.data.items.length === 0 ? (
          <EmptyState
            icon={<IconReserve />}
            title="Sin reservas"
            description={
              can("reservations.write")
                ? "Reserve unidades de una posición para preparar un pedido sin bloquear el almacén físicamente."
                : "No hay reservas que coincidan con el filtro."
            }
            action={
              can("reservations.write") ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={openCreate}>
                  Nueva reserva
                </button>
              ) : undefined
            }
          />
        ) : null}

        {reservations.data && reservations.data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Referencia</th>
                    <th>Producto</th>
                    <th>Posición</th>
                    <th className="num">Cantidad</th>
                    <th>Estado</th>
                    <th>Creada</th>
                    <th>Caduca</th>
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {reservations.data.items.map((reservation) => {
                    const meta = reservationStatusMeta[reservation.status] ?? {
                      tone: "neutral",
                      label: reservation.status,
                    };
                    return (
                      <tr key={reservation.id}>
                        <td className="mono">{reservation.reference}</td>
                        <td>
                          <Link href={`/producto?id=${reservation.product_id}`} className="strong small">
                            {reservation.product_name}
                          </Link>
                          <div className="tiny mono text-muted">{reservation.product_sku}</div>
                        </td>
                        <td>
                          <Link
                            href={`/ubicacion?code=${encodeURIComponent(reservation.location_code)}`}
                            className="code-chip location"
                          >
                            {reservation.location_code}
                          </Link>
                          {reservation.pallet_id ? (
                            <div className="tiny">
                              <Link href={`/pale?id=${reservation.pallet_id}`} className="text-accent">
                                palé
                              </Link>
                            </div>
                          ) : null}
                        </td>
                        <td className="num">{fmtQty(reservation.quantity)}</td>
                        <td>
                          <Badge tone={meta.tone as "success"}>{meta.label}</Badge>
                        </td>
                        <td className="small text-muted nowrap">{fmtDateTime(reservation.created_at)}</td>
                        <td className="small nowrap">
                          {reservation.expires_at ? fmtDateTime(reservation.expires_at) : "—"}
                        </td>
                        <td className="actions">
                          {can("reservations.write") && reservation.status === "active" ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => setReleaseTarget(reservation)}
                            >
                              Liberar
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
              total={reservations.data.total}
              limit={reservations.data.limit}
              offset={reservations.data.offset}
              onChange={setOffset}
            />
          </>
        ) : null}
      </section>

      <div className="alert" style={{ marginTop: 14 }}>
        <strong>Reservar no es mover</strong>
        <span>
          Una reserva descuenta del stock <b>disponible</b> pero la mercancía sigue físicamente en su
          ubicación. La salida real se registra en <Link href="/operaciones">Operaciones</Link> y queda en el
          libro de movimientos.
        </span>
      </div>

      <Modal
        open={open}
        title="Nueva reserva"
        subtitle="Elija producto, posición exacta y referencia del pedido"
        onClose={() => setOpen(false)}
        wide
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="reserve-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Reservar stock
            </button>
          </>
        }
      >
        <form id="reserve-form" className="stack" onSubmit={create}>
          <Field label="Producto" required>
            <ProductPicker value={product?.id ?? null} onChange={setProduct} />
          </Field>
          {product ? (
            whereabouts.loading && !whereabouts.data ? (
              <LoadingBlock label="Consultando posiciones con stock…" />
            ) : positions.length === 0 ? (
              <div className="alert warning">
                <strong>Sin stock disponible</strong>
                <span>Este producto no tiene unidades disponibles. Registre una recepción antes de reservar.</span>
              </div>
            ) : (
              <Field label="Posición con stock" required hint="Solo se muestran posiciones con unidades disponibles">
                <select
                  className="select"
                  value={positionKey}
                  onChange={(event) => {
                    setPositionKey(event.target.value);
                    setQuantity("");
                  }}
                  required
                >
                  <option value="">Seleccione una posición…</option>
                  {positions.map((position) => (
                    <option key={position.key} value={position.key}>
                      {position.locationCode}
                      {position.palletCode ? ` · ${position.palletCode}` : " · estantería"} —{" "}
                      {fmtNumber(position.available, 3)} disponibles
                    </option>
                  ))}
                </select>
              </Field>
            )
          ) : null}
          <div className="form-grid">
            <Field
              label="Cantidad a reservar"
              required
              hint={selected ? `Máximo ${fmtNumber(selected.available, 3)}` : undefined}
            >
              <input
                className="input"
                type="number"
                min="0.001"
                step="0.001"
                max={selected?.available}
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                disabled={!selected}
                required
              />
            </Field>
            <Field label="Referencia del pedido" required>
              <input
                className="input mono"
                value={reference}
                onChange={(event) => setReference(event.target.value)}
                placeholder="PED-2026-0042"
                maxLength={60}
                required
              />
            </Field>
            <Field
              label="Caducidad"
              className="full"
              hint="Opcional. Al llegar esa fecha el servidor libera la reserva y devuelve las unidades a disponible."
            >
              <input
                className="input"
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
              />
            </Field>
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(releaseTarget)}
        title="Liberar reserva"
        message={
          <>
            Se liberarán <b>{releaseTarget ? fmtQty(releaseTarget.quantity) : ""}</b> unidades de{" "}
            <b>{releaseTarget?.product_name}</b> ({releaseTarget?.reference}). Volverán a estar disponibles para
            otras operaciones. No se mueve mercancía física.
          </>
        }
        confirmLabel="Liberar reserva"
        busy={busy}
        onConfirm={release}
        onClose={() => setReleaseTarget(null)}
      />
    </>
  );
}
