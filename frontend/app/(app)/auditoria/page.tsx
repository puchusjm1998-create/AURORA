"use client";

import { useMemo, useState } from "react";
import { useDebounced, useApi } from "@/lib/useApi";
import { withQuery } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { AuditEntry, Page } from "@/lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  Modal,
  PageHeader,
  Pagination,
  SearchInput,
} from "@/components/ui";
import { IconRefresh, IconShield } from "@/components/icons";

const LIMIT = 50;

const ENTITY_LABEL: Record<string, string> = {
  stock_movement: "Movimiento",
  product: "Producto",
  pallet: "Palé",
  location: "Ubicación",
  warehouse: "Almacén",
  invoice: "Factura",
  invoice_line: "Línea de factura",
  user: "Usuario",
  user_session: "Sesión",
  employee: "Trabajador",
  supplier: "Proveedor",
  reservation: "Reserva",
  stock_reservation: "Reserva",
};

export default function AuditPage() {
  const [search, setSearch] = useState("");
  const [entity, setEntity] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const debounced = useDebounced(search, 280);

  const query = useMemo(
    () =>
      withQuery("/api/v1/audit", {
        action: debounced || null,
        entity_type: entity || null,
        date_from: dateFrom ? new Date(`${dateFrom}T00:00:00`).toISOString() : null,
        limit: LIMIT,
        offset,
      }),
    [debounced, entity, dateFrom, offset],
  );
  const { data, error, loading, reload } = useApi<Page<AuditEntry>>(query);

  return (
    <>
      <PageHeader
        eyebrow="Cumplimiento"
        title="Auditoría del sistema"
        subtitle="Registro append-only: las entradas no pueden modificarse ni eliminarse, ni siquiera desde la base de datos."
        actions={
          <button type="button" className="btn btn-ghost" onClick={reload} disabled={loading}>
            <IconRefresh /> Actualizar
          </button>
        }
      />

      <section className="card">
        <div className="toolbar">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder="Buscar por acción (auth.login, movement.confirmed…)"
          />
          <select
            className="select"
            value={entity}
            onChange={(event) => {
              setEntity(event.target.value);
              setOffset(0);
            }}
            aria-label="Entidad"
          >
            <option value="">Todas las entidades</option>
            {Object.entries(ENTITY_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
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
            style={{ width: 160 }}
          />
          <span className="spacer" />
          <span className="count-chip">{data ? `${data.total} eventos` : "—"}</span>
        </div>

        {error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={error} onRetry={reload} />
          </div>
        ) : null}
        {loading && !data ? <LoadingBlock label="Consultando auditoría…" /> : null}
        {data && data.items.length === 0 ? (
          <EmptyState icon={<IconShield />} title="Sin eventos" description="No hay registros que coincidan con los filtros." />
        ) : null}

        {data && data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Actor</th>
                    <th>Acción</th>
                    <th>Entidad</th>
                    <th>ID</th>
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((entry) => (
                    <tr key={entry.id}>
                      <td className="small nowrap">{fmtDateTime(entry.created_at)}</td>
                      <td className="small">{entry.actor_label}</td>
                      <td>
                        <span className="mono small">{entry.action}</span>
                      </td>
                      <td className="small">
                        <Badge tone="neutral" dot={false}>
                          {ENTITY_LABEL[entry.entity_type] ?? entry.entity_type}
                        </Badge>
                      </td>
                      <td className="mono tiny text-muted truncate" style={{ maxWidth: 170 }}>
                        {entry.entity_id ?? "—"}
                      </td>
                      <td className="actions">
                        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setSelected(entry)}>
                          Detalle
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={data.total} limit={data.limit} offset={data.offset} onChange={setOffset} />
          </>
        ) : null}
      </section>

      <div className="alert" style={{ marginTop: 14 }}>
        <strong>Protección reforzada</strong>
        <span>
          Cada cambio se escribe en la misma transacción que la operación auditada. Triggers de base de datos
          rechazan cualquier UPDATE o DELETE sobre <code className="inline-code">audit_logs</code> y la
          eliminación de movimientos.
        </span>
      </div>

      <Modal
        open={Boolean(selected)}
        title={selected ? selected.action : ""}
        subtitle={selected ? `${selected.actor_label} · ${fmtDateTime(selected.created_at)}` : undefined}
        onClose={() => setSelected(null)}
        wide
        footer={
          <button type="button" className="btn btn-ghost" onClick={() => setSelected(null)}>
            Cerrar
          </button>
        }
      >
        {selected ? (
          <div className="stack">
            <dl className="def-list">
              <div className="def-row">
                <dt>Entidad</dt>
                <dd>{ENTITY_LABEL[selected.entity_type] ?? selected.entity_type}</dd>
              </div>
              <div className="def-row">
                <dt>Identificador</dt>
                <dd className="mono">{selected.entity_id ?? "—"}</dd>
              </div>
              <div className="def-row">
                <dt>Registro</dt>
                <dd className="mono tiny">{selected.id}</dd>
              </div>
            </dl>
            <div>
              <div className="section-title" style={{ marginBottom: 6 }}>Estado anterior</div>
              <pre className="inline-code" style={{ display: "block", whiteSpace: "pre-wrap", maxHeight: 220, overflow: "auto" }}>
                {selected.before ? JSON.stringify(selected.before, null, 2) : "—"}
              </pre>
            </div>
            <div>
              <div className="section-title" style={{ marginBottom: 6 }}>Estado posterior</div>
              <pre className="inline-code" style={{ display: "block", whiteSpace: "pre-wrap", maxHeight: 220, overflow: "auto" }}>
                {selected.after ? JSON.stringify(selected.after, null, 2) : "—"}
              </pre>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
