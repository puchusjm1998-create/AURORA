"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import {
  DIRECTION_LABELS,
  MOVEMENT_TYPES,
  fmtDateTime,
  fmtQty,
  movementBadge,
  movementDirection,
  movementLabel,
} from "@/lib/format";
import type { Movement, Page } from "@/lib/types";
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
  useToast,
} from "@/components/ui";
import { IconArrowIn, IconArrowOut, IconMovements, IconRefresh, IconScan } from "@/components/icons";

const LIMIT = 40;

function MovementsView() {
  const params = useSearchParams();
  const { can } = useAuth();
  const toast = useToast();
  const [search, setSearch] = useState(params.get("search") ?? "");
  const [productFilter] = useState(params.get("product") ?? "");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Movement | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Movement | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [busy, setBusy] = useState(false);
  const debounced = useDebounced(search, 280);

  const query = useMemo(
    () =>
      withQuery("/api/v1/movements", {
        search: debounced || null,
        movement_type: type || null,
        status: status || null,
        product_id: productFilter || null,
        date_from: dateFrom ? new Date(`${dateFrom}T00:00:00`).toISOString() : null,
        date_to: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : null,
        limit: LIMIT,
        offset,
      }),
    [debounced, type, status, productFilter, dateFrom, dateTo, offset],
  );
  const { data, error, loading, reload } = useApi<Page<Movement>>(query);

  async function confirmMovement(movement: Movement) {
    setBusy(true);
    try {
      await api(`/api/v1/movements/${movement.id}/confirm`, {
        method: "POST",
        body: { physical_confirmed: true },
      });
      toast.success("Movimiento confirmado", movement.reference);
      setSelected(null);
      reload();
    } catch (err) {
      toast.error("No se pudo confirmar", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelMovement() {
    if (!cancelTarget) return;
    setBusy(true);
    try {
      await api(`/api/v1/movements/${cancelTarget.id}/cancel`, {
        method: "POST",
        body: { reason: cancelReason.trim() },
      });
      toast.success("Movimiento cancelado", cancelTarget.reference);
      setCancelTarget(null);
      setCancelReason("");
      setSelected(null);
      reload();
    } catch (err) {
      toast.error("No se pudo cancelar", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Libro de stock"
        title="Historial de movimientos"
        subtitle="Registro inmutable con trabajador, origen, destino, documento y confirmación física. Horas en Europe/Madrid."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={reload} disabled={loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("movements.write") ? (
              <Link href={productFilter ? `/operaciones?product=${productFilter}` : "/operaciones"} className="btn btn-primary">
                <IconScan /> Nueva operación
              </Link>
            ) : null}
          </>
        }
      />

      {productFilter ? (
        <div className="alert" style={{ marginBottom: 14 }}>
          <span>
            Mostrando movimientos de un producto concreto.{" "}
            <Link href="/movimientos" className="text-accent">
              Quitar filtro
            </Link>
          </span>
        </div>
      ) : null}

      <section className="card">
        <div className="toolbar">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder="Buscar por referencia, producto, documento o motivo…"
          />
          <select
            className="select"
            value={type}
            onChange={(event) => {
              setType(event.target.value);
              setOffset(0);
            }}
            aria-label="Tipo de movimiento"
          >
            <option value="">Todos los tipos</option>
            {MOVEMENT_TYPES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            aria-label="Estado"
          >
            <option value="">Cualquier estado</option>
            <option value="confirmed">Confirmado</option>
            <option value="draft">Borrador</option>
            <option value="cancelled">Cancelado</option>
          </select>
          <input
            className="input"
            type="date"
            value={dateFrom}
            onChange={(event) => {
              setDateFrom(event.target.value);
              setOffset(0);
            }}
            aria-label="Desde"
            style={{ width: 150 }}
          />
          <input
            className="input"
            type="date"
            value={dateTo}
            onChange={(event) => {
              setDateTo(event.target.value);
              setOffset(0);
            }}
            aria-label="Hasta"
            style={{ width: 150 }}
          />
          <span className="count-chip">{data ? `${data.total} movimientos` : "—"}</span>
        </div>

        {error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={error} onRetry={reload} />
          </div>
        ) : null}
        {loading && !data ? <LoadingBlock label="Consultando historial…" /> : null}
        {data && data.items.length === 0 ? (
          <EmptyState
            icon={<IconMovements />}
            title="Sin movimientos"
            description="No hay operaciones registradas con estos filtros."
            action={
              can("movements.write") ? (
                <Link href="/operaciones" className="btn btn-sm btn-primary">
                  Registrar movimiento
                </Link>
              ) : undefined
            }
          />
        ) : null}

        {data && data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Referencia</th>
                    <th>Tipo</th>
                    <th>Producto</th>
                    <th className="num">Cantidad</th>
                    <th>Origen → destino</th>
                    <th>Trabajador</th>
                    <th>Física</th>
                    <th>Estado</th>
                    <th>Fecha</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((movement) => {
                    const statusMeta = movementBadge[movement.status];
                    const dir = movementDirection(movement.movement_type);
                    return (
                      <tr
                        key={movement.id}
                        className="row-link"
                        onClick={() => setSelected(movement)}
                      >
                        <td className="mono">
                          <span className={dir === "in" ? "text-success" : dir === "out" ? "text-warning" : "text-accent"}>
                            {movement.reference}
                          </span>
                        </td>
                        <td>
                          <div className="small strong">{movementLabel(movement.movement_type)}</div>
                          <div className="tiny text-muted">{DIRECTION_LABELS[movement.movement_type]}</div>
                        </td>
                        <td>
                          <div className="strong small">{movement.product_name}</div>
                          <div className="tiny mono text-muted">{movement.product_sku}</div>
                        </td>
                        <td className="num">
                          {dir === "in" ? "+" : dir === "out" ? "−" : ""}
                          {fmtQty(movement.quantity, movement.uom)}
                        </td>
                        <td className="mono tiny text-muted">
                          {movement.from_location_code ?? "—"} → {movement.to_location_code ?? "—"}
                        </td>
                        <td className="small">{movement.worker_name ?? "—"}</td>
                        <td>
                          {movement.physical_confirmed ? (
                            <Badge tone="success" dot={false}>Sí</Badge>
                          ) : (
                            <Badge tone="neutral" dot={false}>No</Badge>
                          )}
                        </td>
                        <td>
                          <Badge tone={statusMeta.tone as "success"}>{statusMeta.label}</Badge>
                        </td>
                        <td className="small text-muted nowrap">{fmtDateTime(movement.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination total={data.total} limit={data.limit} offset={data.offset} onChange={setOffset} />
          </>
        ) : null}
      </section>

      <Modal
        open={Boolean(selected)}
        title={selected ? `Movimiento ${selected.reference}` : ""}
        subtitle={selected ? movementLabel(selected.movement_type) : undefined}
        onClose={() => setSelected(null)}
        wide
        footer={
          selected ? (
            <>
              {selected.status === "draft" && can("movements.confirm") ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => confirmMovement(selected)}
                  disabled={busy}
                >
                  {busy ? <span className="spinner" /> : null} Confirmar movimiento
                </button>
              ) : null}
              {selected.status === "draft" && can("movements.cancel") ? (
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => {
                    setCancelTarget(selected);
                    setCancelReason("");
                  }}
                  disabled={busy}
                >
                  Cancelar movimiento
                </button>
              ) : null}
              <button type="button" className="btn btn-ghost" onClick={() => setSelected(null)}>
                Cerrar
              </button>
            </>
          ) : null
        }
      >
        {selected ? (
          <div className="stack">
            <div className="row" style={{ gap: 8 }}>
              <Badge tone={movementBadge[selected.status].tone as "success"}>
                {movementBadge[selected.status].label}
              </Badge>
              <Badge tone="neutral" dot={false}>
                {DIRECTION_LABELS[selected.movement_type]}
              </Badge>
              <Badge tone={selected.physical_confirmed ? "success" : "warning"}>
                Confirmación física: {selected.physical_confirmed ? "sí" : "no"}
              </Badge>
            </div>

            <dl className="def-list">
              <div className="def-row">
                <dt>Producto</dt>
                <dd>
                  <Link href={`/producto?id=${selected.product_id}`} className="text-accent">
                    {selected.product_name}
                  </Link>{" "}
                  <span className="mono tiny text-muted">{selected.product_sku}</span>
                </dd>
              </div>
              <div className="def-row">
                <dt>Cantidad</dt>
                <dd>
                  {fmtQty(selected.quantity, selected.uom)}
                  {selected.batch_code ? ` · lote ${selected.batch_code}` : ""}
                </dd>
              </div>
              <div className="def-row">
                <dt>Origen</dt>
                <dd className="mono">{selected.from_location_code ?? "—"}</dd>
              </div>
              <div className="def-row">
                <dt>Destino</dt>
                <dd className="mono">{selected.to_location_code ?? "—"}</dd>
              </div>
              <div className="def-row">
                <dt>Trabajador</dt>
                <dd>{selected.worker_name ?? "No asignado"}</dd>
              </div>
              <div className="def-row">
                <dt>Registrado por</dt>
                <dd>{selected.created_by_name ?? "—"}</dd>
              </div>
              <div className="def-row">
                <dt>Motivo</dt>
                <dd>{selected.reason || "—"}</dd>
              </div>
              <div className="def-row">
                <dt>Documento</dt>
                <dd className="mono">{selected.document_ref || "—"}</dd>
              </div>
              <div className="def-row">
                <dt>Creado</dt>
                <dd>{fmtDateTime(selected.created_at)}</dd>
              </div>
              <div className="def-row">
                <dt>Confirmado</dt>
                <dd>{fmtDateTime(selected.confirmed_at)}</dd>
              </div>
            </dl>

            {selected.allocations.length ? (
              <div>
                <div className="section-title" style={{ marginBottom: 8 }}>
                  Desglose por ubicación
                </div>
                <div className="table-wrap">
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th>Ubicación</th>
                        <th>Palé</th>
                        <th className="num">Efecto</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.allocations.map((allocation, index) => (
                        <tr key={index}>
                          <td className="mono">{allocation.location_code}</td>
                          <td className="mono small">{allocation.pallet_code ?? "—"}</td>
                          <td className="num">{fmtQty(allocation.quantity)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}

            {selected.unit_codes.length ? (
              <div>
                <div className="section-title" style={{ marginBottom: 8 }}>
                  Unidades afectadas
                </div>
                <div className="row" style={{ gap: 6 }}>
                  {selected.unit_codes.map((code) => (
                    <span className="code-chip" key={code}>
                      {code}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {selected.status === "draft" ? (
              <div className="alert warning">
                <strong>Movimiento en borrador</strong>
                <span>Este movimiento todavía no ha modificado el stock. Debe confirmarse para aplicarlo.</span>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(cancelTarget)}
        title="Cancelar movimiento"
        subtitle={cancelTarget?.reference}
        onClose={() => setCancelTarget(null)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setCancelTarget(null)} disabled={busy}>
              Volver
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={cancelMovement}
              disabled={busy || cancelReason.trim().length < 3}
            >
              {busy ? <span className="spinner" /> : null} Confirmar cancelación
            </button>
          </>
        }
      >
        <Field label="Motivo de la cancelación" required>
          <textarea
            className="textarea"
            value={cancelReason}
            onChange={(event) => setCancelReason(event.target.value)}
            placeholder="Explique por qué se anula el movimiento (mínimo 3 caracteres)"
          />
        </Field>
        <p className="hint">
          Solo pueden cancelarse movimientos en borrador. Los movimientos confirmados son inmutables y
          requieren un ajuste autorizado para corregir el stock.
        </p>
      </Modal>
    </>
  );
}

export default function MovementsPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <MovementsView />
    </Suspense>
  );
}
