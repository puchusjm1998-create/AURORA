"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { fmtNumber } from "@/lib/format";
import type { Location, Page, Warehouse, WarehouseLayout } from "@/lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  useToast,
} from "@/components/ui";
import { IconPlus, IconPrint, IconQr, IconRefresh, IconWarehouse } from "@/components/icons";

function WarehouseDetail() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const { can } = useAuth();
  const toast = useToast();
  const warehouse = useApi<Warehouse>(id ? `/api/v1/warehouses/${id}` : null, [id]);
  const layout = useApi<WarehouseLayout>(id ? `/api/v1/warehouses/${id}/layout` : null, [id]);
  const locations = useApi<Page<Location>>(
    id ? `/api/v1/locations?warehouse_id=${id}&limit=500` : null,
    [id],
  );

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [form, setForm] = useState({
    aisle: "P01",
    rack: "EA",
    level: "N01",
    position: "POS01",
    label: "",
    capacity_pallets: "1",
    is_pick_face: false,
  });

  const previewCode = warehouse.data
    ? `${warehouse.data.code}-${form.aisle.toUpperCase()}-${form.rack.toUpperCase()}-${form.level.toUpperCase()}-${form.position.toUpperCase()}`
    : "";

  async function createLocation(event: React.FormEvent) {
    event.preventDefault();
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      await api<Location>("/api/v1/locations", {
        method: "POST",
        body: {
          warehouse_id: id,
          aisle: form.aisle,
          rack: form.rack,
          level: form.level,
          position: form.position,
          label: form.label,
          capacity_pallets: Number(form.capacity_pallets) || 0,
          is_pick_face: form.is_pick_face,
        },
      });
      toast.success("Ubicación creada", previewCode);
      setOpen(false);
      setForm({ ...form, label: "" });
      layout.reload();
      locations.reload();
      warehouse.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function toggle(idValue: string) {
    const next = new Set(selected);
    if (next.has(idValue)) next.delete(idValue);
    else next.add(idValue);
    setSelected(next);
  }

  if (!id) {
    return <EmptyState title="Almacén no indicado" description="Selecciona un almacén desde el listado." action={<Link href="/almacenes" className="btn btn-primary btn-sm">Ver almacenes</Link>} />;
  }
  if (warehouse.error) return <ErrorBlock message={warehouse.error} onRetry={warehouse.reload} />;
  if (warehouse.loading || !warehouse.data) return <LoadingBlock label="Cargando almacén…" />;

  const data = warehouse.data;

  return (
    <>
      <PageHeader
        eyebrow={`Almacén ${data.code}`}
        title={data.name}
        subtitle={`${data.address || "Sin dirección"} · ${data.postal_code} ${data.city} · ${data.location_count} ubicaciones`}
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => { layout.reload(); locations.reload(); }} disabled={layout.loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("locations.write") ? (
              <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
                <IconPlus /> Nueva ubicación
              </button>
            ) : null}
          </>
        }
      />

      <div className="stack" style={{ gap: 18 }}>
        <Card
          title="Mapa de ocupación"
          subtitle="Cada celda es una posición física. El color indica ocupación."
          actions={
            <div className="row tight">
              <span className="tag-pill">Verde: disponible</span>
              <span className="tag-pill">Ámbar: llena</span>
            </div>
          }
        >
          {layout.loading && !layout.data ? <LoadingBlock label="Dibujando mapa…" /> : null}
          {layout.data && layout.data.aisles.length === 0 ? (
            <EmptyState
              icon={<IconWarehouse />}
              title="Sin ubicaciones"
              description="Crea al menos una ubicación para poder almacenar mercancía."
              action={
                can("locations.write") ? (
                  <button type="button" className="btn btn-sm btn-primary" onClick={() => setOpen(true)}>
                    Crear ubicación
                  </button>
                ) : undefined
              }
            />
          ) : null}
          <div className="stack" style={{ gap: 18 }}>
            {layout.data?.aisles.map((aisle) => (
              <div className="aisle-card" key={aisle.aisle}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="section-title">Pasillo {aisle.aisle}</span>
                  <span className="tiny text-muted">{aisle.racks.reduce((acc, rack) => acc + rack.locations.length, 0)} posiciones</span>
                </div>
                {aisle.racks.map((rack) => (
                  <div className="rack-block" key={rack.rack}>
                    <div className="rack-title">Estantería {rack.rack}</div>
                    <div className="location-grid">
                      {rack.locations.map((location) => {
                        const full = location.occupied_pallets >= location.capacity_pallets && location.capacity_pallets > 0;
                        const empty = Number(location.occupied_units) === 0;
                        const pct = location.capacity_pallets
                          ? Math.min(100, Math.round((location.occupied_pallets / location.capacity_pallets) * 100))
                          : 0;
                        return (
                          <Link
                            key={location.id}
                            href={`/ubicacion?code=${encodeURIComponent(location.full_code)}`}
                            className={`location-cell ${full ? "full" : ""} ${empty ? "empty" : ""}`}
                            title={`${location.full_code} · ${fmtNumber(location.occupied_units, 3)} unidades`}
                          >
                            <span className="lc-code">{location.level}/{location.position}</span>
                            <span className="lc-fill">
                              <i style={{ width: `${pct || (empty ? 0 : 100)}%` }} />
                            </span>
                            <span className="lc-qty">{fmtNumber(location.occupied_units, 0)} uds</span>
                          </Link>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="Ubicaciones"
          subtitle="Selecciona ubicaciones para imprimir sus etiquetas QR"
          flush
          actions={
            <div className="row tight">
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setSelected(new Set())}>
                Limpiar
              </button>
              <Link
                href={`/etiquetas?kind=location&ids=${Array.from(selected).join(",")}`}
                className={`btn btn-sm ${selected.size ? "btn-primary" : "btn-ghost"}`}
                aria-disabled={!selected.size}
                onClick={(event) => {
                  if (!selected.size) event.preventDefault();
                }}
              >
                <IconPrint /> Imprimir {selected.size || ""}
              </Link>
            </div>
          }
        >
          {locations.loading && !locations.data ? <LoadingBlock /> : null}
          {locations.data?.items.length === 0 ? (
            <EmptyState title="Sin ubicaciones registradas" />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 36 }} />
                    <th>Código</th>
                    <th>Pasillo / estantería</th>
                    <th>Nivel / posición</th>
                    <th className="num">Palés</th>
                    <th className="num">Unidades</th>
                    <th>Picking</th>
                    <th className="actions">QR</th>
                  </tr>
                </thead>
                <tbody>
                  {locations.data?.items.map((location) => (
                    <tr key={location.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.has(location.id)}
                          onChange={() => toggle(location.id)}
                          aria-label={`Seleccionar ${location.full_code}`}
                        />
                      </td>
                      <td className="mono">
                        <Link href={`/ubicacion?code=${encodeURIComponent(location.full_code)}`} className="text-accent">
                          {location.full_code}
                        </Link>
                      </td>
                      <td className="small">{location.aisle} / {location.rack}</td>
                      <td className="small">{location.level} / {location.position}</td>
                      <td className="num">
                        {location.occupied_pallets}/{location.capacity_pallets}
                      </td>
                      <td className="num">{fmtNumber(location.occupied_units, 3)}</td>
                      <td>{location.is_pick_face ? <Badge tone="accent">Picking</Badge> : <span className="text-muted small">—</span>}</td>
                      <td className="actions">
                        <Link href={`/etiquetas?kind=location&ids=${location.id}`} className="btn btn-sm btn-ghost">
                          <IconQr />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Modal
        open={open}
        title="Nueva ubicación"
        subtitle="El código se genera automáticamente y no podrá modificarse"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="create-location" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Crear ubicación
            </button>
          </>
        }
      >
        <form id="create-location" className="stack" onSubmit={createLocation}>
          <div className="form-grid">
            <Field label="Pasillo" required>
              <input className="input mono" value={form.aisle} onChange={(event) => setForm({ ...form, aisle: event.target.value.toUpperCase() })} required />
            </Field>
            <Field label="Estantería" required>
              <input className="input mono" value={form.rack} onChange={(event) => setForm({ ...form, rack: event.target.value.toUpperCase() })} required />
            </Field>
            <Field label="Nivel" required>
              <input className="input mono" value={form.level} onChange={(event) => setForm({ ...form, level: event.target.value.toUpperCase() })} required />
            </Field>
            <Field label="Posición" required>
              <input className="input mono" value={form.position} onChange={(event) => setForm({ ...form, position: event.target.value.toUpperCase() })} required />
            </Field>
            <Field label="Capacidad de palés" hint="Número máximo de palés en la posición">
              <input
                className="input"
                type="number"
                min="0"
                max="1000"
                value={form.capacity_pallets}
                onChange={(event) => setForm({ ...form, capacity_pallets: event.target.value })}
              />
            </Field>
            <Field label="Etiqueta descriptiva">
              <input className="input" value={form.label} onChange={(event) => setForm({ ...form, label: event.target.value })} placeholder="Ej. Picking EPI" />
            </Field>
            <div className="full">
              <label className="check">
                <input
                  type="checkbox"
                  checked={form.is_pick_face}
                  onChange={(event) => setForm({ ...form, is_pick_face: event.target.checked })}
                />
                Ubicación de picking (acceso preferente)
              </label>
            </div>
            <div className="full">
              <div className="alert">
                <strong>Código resultante</strong>
                <span className="mono text-accent">{previewCode || "—"}</span>
              </div>
            </div>
            <div className="full">{error ? <div className="form-error">{error}</div> : null}</div>
          </div>
        </form>
      </Modal>
    </>
  );
}

export default function WarehousePage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <WarehouseDetail />
    </Suspense>
  );
}
