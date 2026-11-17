"use client";

import Link from "next/link";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { fmtNumber } from "@/lib/format";
import type { Page, Warehouse } from "@/lib/types";
import {
  Card,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  useToast,
} from "@/components/ui";
import { IconPin, IconPlus, IconRefresh, IconWarehouse } from "@/components/icons";

export default function WarehousesPage() {
  const { can } = useAuth();
  const toast = useToast();
  const warehouses = useApi<Page<Warehouse>>("/api/v1/warehouses");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    code: "ALM-",
    name: "",
    address: "",
    city: "",
    postal_code: "",
    country: "ES",
  });

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const warehouse = await api<Warehouse>("/api/v1/warehouses", {
        method: "POST",
        body: form,
      });
      toast.success("Almacén creado", `${warehouse.code} · ${warehouse.name}`);
      setOpen(false);
      setForm({ code: "ALM-", name: "", address: "", city: "", postal_code: "", country: "ES" });
      warehouses.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Infraestructura"
        title="Almacenes y ubicaciones"
        subtitle="Jerarquía física: almacén → pasillo → estantería → nivel → posición. Cada posición tiene su código y su QR."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={warehouses.reload} disabled={warehouses.loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("locations.write") ? (
              <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
                <IconPlus /> Nuevo almacén
              </button>
            ) : null}
          </>
        }
      />

      {warehouses.error ? <ErrorBlock message={warehouses.error} onRetry={warehouses.reload} /> : null}
      {warehouses.loading && !warehouses.data ? <LoadingBlock label="Cargando almacenes…" /> : null}

      {warehouses.data && warehouses.data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconWarehouse />}
            title="Sin almacenes"
            description="Crea el primer almacén y define su primera ubicación para poder recibir mercancía."
            action={
              can("locations.write") ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setOpen(true)}>
                  Crear almacén
                </button>
              ) : undefined
            }
          />
        </Card>
      ) : null}

      <div className="grid grid-2">
        {warehouses.data?.items.map((warehouse) => (
          <Card key={warehouse.id}>
            <div className="stack" style={{ gap: 12 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <span className="mono text-accent">{warehouse.code}</span>
                  <h2 style={{ fontSize: 19, marginTop: 2 }}>{warehouse.name}</h2>
                </div>
                <span className="tag-pill">
                  {warehouse.location_count} ubicaciones
                </span>
              </div>
              <div className="detail-meta">
                <span>
                  <b>{warehouse.address || "Sin dirección"}</b>
                </span>
                <span>
                  {warehouse.postal_code} {warehouse.city} · {warehouse.country}
                </span>
                <span>
                  Zona horaria: <b>{warehouse.timezone}</b>
                </span>
              </div>
              <div className="row">
                <Link href={`/almacen?id=${warehouse.id}`} className="btn btn-sm btn-primary">
                  <IconPin /> Ver mapa y ubicaciones
                </Link>
                <Link href={`/inventario`} className="btn btn-sm btn-ghost">
                  Inventario
                </Link>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="alert" style={{ marginTop: 18 }}>
        <strong>Codificación de ubicaciones</strong>
        <span>
          El código se compone automáticamente: <code className="inline-code">ALM-01</code> +{" "}
          <code className="inline-code">P04</code> (pasillo) + <code className="inline-code">EB</code>{" "}
          (estantería) + <code className="inline-code">N02</code> (nivel) +{" "}
          <code className="inline-code">POS03</code> (posición) ={" "}
          <code className="inline-code">ALM-01-P04-EB-N02-POS03</code>. El código es único y no reutilizable.
        </span>
      </div>

      <Modal
        open={open}
        title="Nuevo almacén"
        subtitle="El código se usa como prefijo de todas sus ubicaciones"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="create-warehouse" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Crear almacén
            </button>
          </>
        }
      >
        <form id="create-warehouse" onSubmit={create} className="form-grid">
          <Field label="Código" required hint="Mayúsculas, números y guiones. Ej. ALM-01">
            <input
              className="input mono"
              value={form.code}
              onChange={(event) => setForm({ ...form, code: event.target.value.toUpperCase() })}
              required
              pattern="[A-Z0-9\-]{2,20}"
            />
          </Field>
          <Field label="Nombre" required>
            <input
              className="input"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </Field>
          <Field label="Dirección" className="full">
            <input
              className="input"
              value={form.address}
              onChange={(event) => setForm({ ...form, address: event.target.value })}
            />
          </Field>
          <Field label="Ciudad">
            <input
              className="input"
              value={form.city}
              onChange={(event) => setForm({ ...form, city: event.target.value })}
            />
          </Field>
          <Field label="Código postal">
            <input
              className="input"
              value={form.postal_code}
              onChange={(event) => setForm({ ...form, postal_code: event.target.value })}
            />
          </Field>
          <Field label="País" hint="Código ISO de 2 letras">
            <input
              className="input mono"
              value={form.country}
              onChange={(event) => setForm({ ...form, country: event.target.value.toUpperCase() })}
              maxLength={2}
            />
          </Field>
          <div className="full">{error ? <div className="form-error">{error}</div> : null}</div>
        </form>
      </Modal>
    </>
  );
}
