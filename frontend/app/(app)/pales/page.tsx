"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import { fmtDateTime, fmtNumber, palletStatusMeta } from "@/lib/format";
import type { Page, Pallet, Warehouse } from "@/lib/types";
import { LocationPicker } from "@/components/pickers";
import {
  Badge,
  Card,
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
import { IconPallet, IconPlus, IconQr, IconRefresh } from "@/components/icons";

const LIMIT = 20;

export default function PalletsPage() {
  const router = useRouter();
  const { can } = useAuth();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    warehouse_id: "",
    location_id: "",
    location_code: "",
    notes: "",
    weight: "",
  });
  const debounced = useDebounced(search, 280);

  const warehouses = useApi<Page<Warehouse>>("/api/v1/warehouses");
  const query = useMemo(
    () =>
      withQuery("/api/v1/pallets", {
        search: debounced || null,
        status: status || null,
        limit: LIMIT,
        offset,
      }),
    [debounced, status, offset],
  );
  const { data, error: loadError, loading, reload } = useApi<Page<Pallet>>(query);

  async function createPallet(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!form.warehouse_id) {
      setError("Seleccione un almacén.");
      return;
    }
    setBusy(true);
    try {
      const pallet = await api<Pallet>("/api/v1/pallets", {
        method: "POST",
        body: {
          warehouse_id: form.warehouse_id,
          location_id: form.location_id || null,
          notes: form.notes,
          gross_weight_kg: form.weight ? form.weight : null,
        },
      });
      toast.success("Palé creado", `${pallet.code} listo para estocar mercancía.`);
      setCreating(false);
      setForm({ warehouse_id: "", location_id: "", location_code: "", notes: "", weight: "" });
      router.push(`/pale?id=${pallet.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Unidad logística"
        title="Palés"
        subtitle="Identificadores AUR-PAL únicos y persistentes. Cada palé conoce su ubicación, su contenido y su historial."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={reload} disabled={loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("pallets.write") ? (
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                <IconPlus /> Nuevo palé
              </button>
            ) : null}
          </>
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
            placeholder="Buscar por código de palé o producto…"
          />
          <select
            className="select"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            aria-label="Estado del palé"
          >
            <option value="">Cualquier estado</option>
            <option value="open">Abierto</option>
            <option value="sealed">Precintado</option>
            <option value="shipped">Expedido</option>
            <option value="in_transit">En tránsito</option>
          </select>
          <span className="spacer" />
          <span className="count-chip">{data ? `${data.total} palés` : "—"}</span>
        </div>

        {loadError ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={loadError} onRetry={reload} />
          </div>
        ) : null}
        {loading && !data ? <LoadingBlock label="Consultando palés…" /> : null}
        {data && data.items.length === 0 ? (
          <EmptyState
            icon={<IconPallet />}
            title="Sin palés"
            description="Crea un palé, asígnale ubicación y añade mercancía para empezar la trazabilidad."
            action={
              can("pallets.write") ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setCreating(true)}>
                  <IconPlus /> Crear palé
                </button>
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
                    <th>Código</th>
                    <th>Estado</th>
                    <th>Ubicación</th>
                    <th className="num">Referencias</th>
                    <th className="num">Unidades</th>
                    <th>Creado</th>
                    <th className="actions">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((pallet) => {
                    const meta = palletStatusMeta[pallet.status];
                    return (
                      <tr key={pallet.id}>
                        <td className="mono">
                          <Link href={`/pale?id=${pallet.id}`} className="text-accent">
                            {pallet.code}
                          </Link>
                        </td>
                        <td>
                          <Badge tone={meta.tone as "success"}>{meta.label}</Badge>
                        </td>
                        <td>
                          {pallet.location_code ? (
                            <span className="code-chip location">{pallet.location_code}</span>
                          ) : (
                            <span className="text-muted small">Sin ubicación</span>
                          )}
                        </td>
                        <td className="num">{pallet.item_count}</td>
                        <td className="num">{fmtNumber(pallet.total_units, 3)}</td>
                        <td className="small text-muted nowrap">{fmtDateTime(pallet.created_at)}</td>
                        <td className="actions">
                          <div className="row tight" style={{ justifyContent: "flex-end" }}>
                            <Link href={`/pale?id=${pallet.id}`} className="btn btn-sm btn-ghost">
                              Ver
                            </Link>
                            <Link
                              href={`/etiquetas?kind=pallet&ids=${pallet.id}`}
                              className="btn btn-sm btn-ghost"
                              aria-label={`Etiqueta de ${pallet.code}`}
                            >
                              <IconQr />
                            </Link>
                          </div>
                        </td>
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
        open={creating}
        title="Crear palé"
        subtitle="Se asignará el siguiente código AUR-PAL disponible"
        onClose={() => setCreating(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setCreating(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="create-pallet" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Crear palé
            </button>
          </>
        }
      >
        <form id="create-pallet" onSubmit={createPallet} className="stack">
          <Field label="Almacén" required>
            <select
              className="select"
              value={form.warehouse_id}
              onChange={(event) => setForm({ ...form, warehouse_id: event.target.value, location_id: "" })}
              required
            >
              <option value="">Seleccione almacén…</option>
              {warehouses.data?.items.map((warehouse) => (
                <option key={warehouse.id} value={warehouse.id}>
                  {warehouse.code} · {warehouse.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Ubicación inicial (opcional)" hint="Puede asignarse después, antes de añadir mercancía.">
            <LocationPicker
              value={form.location_id || null}
              onChange={(location) =>
                setForm({
                  ...form,
                  location_id: location?.id ?? "",
                  location_code: location?.full_code ?? "",
                })
              }
              disabled={!form.warehouse_id}
            />
          </Field>
          <Field label="Peso bruto (kg)">
            <input
              className="input"
              type="number"
              min="0"
              step="0.01"
              value={form.weight}
              onChange={(event) => setForm({ ...form, weight: event.target.value })}
            />
          </Field>
          <Field label="Observaciones">
            <textarea
              className="textarea"
              value={form.notes}
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
              placeholder="Ej. recepción factura TPK-2026/1180"
            />
          </Field>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <div className="alert" style={{ marginTop: 14 }}>
        <strong>Cómo se construye un palé</strong>
        <span>
          Crea el palé, asígnale ubicación y añade referencias. Cada alta genera una recepción real en el
          libro de stock. Al precintarlo queda cerrado; después puede reubicarse o expedirse.
        </span>
      </div>
    </>
  );
}
