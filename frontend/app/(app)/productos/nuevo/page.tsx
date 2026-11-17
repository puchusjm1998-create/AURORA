"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Page, Product, Supplier } from "@/lib/types";
import { Card, Field, PageHeader, useToast } from "@/components/ui";
import { IconArrowIn, IconBox } from "@/components/icons";

export default function NewProductPage() {
  const router = useRouter();
  const toast = useToast();
  const suppliers = useApi<Page<Supplier>>("/api/v1/suppliers");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    sku: "",
    description: "",
    category: "General",
    manufacturer_ref: "",
    barcode: "",
    supplier_id: "",
    uom: "ud",
    purchase_price: "0",
    unit_price: "0",
    min_stock: "0",
    tracking_mode: "quantity",
  });

  const update = (field: keyof typeof form, value: string) => setForm({ ...form, [field]: value });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api<Product>("/api/v1/products", {
        method: "POST",
        body: {
          ...form,
          sku: form.sku.trim() ? form.sku.trim().toUpperCase() : null,
          supplier_id: form.supplier_id || null,
          manufacturer_ref: form.manufacturer_ref || null,
          barcode: form.barcode || null,
        },
      });
      toast.success("Producto creado", `${created.sku} · ${created.name}`);
      router.push(`/producto?id=${created.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Catálogo"
        title="Nuevo producto"
        subtitle="Crea la ficha maestra. Después podrás recibir stock y ubicarlo en un palé."
        actions={
          <Link href="/inventario" className="btn btn-ghost">
            <IconBox /> Volver al inventario
          </Link>
        }
      />

      <form onSubmit={submit} className="split">
        <Card title="Datos del producto" subtitle="Los campos con * son obligatorios">
          <div className="form-grid">
            <Field label="Nombre" required className="full">
              <input
                className="input"
                value={form.name}
                onChange={(event) => update("name", event.target.value)}
                required
                maxLength={180}
                placeholder="Ej. Guantes anticorte nivel 5"
              />
            </Field>
            <Field label="SKU interno" hint="Si lo dejas vacío, AURORA genera AUR-SKU-…">
              <input
                className="input mono"
                value={form.sku}
                onChange={(event) => update("sku", event.target.value)}
                placeholder="AUR-SKU-000001"
                maxLength={40}
              />
            </Field>
            <Field label="Referencia del fabricante">
              <input
                className="input"
                value={form.manufacturer_ref}
                onChange={(event) => update("manufacturer_ref", event.target.value)}
                maxLength={80}
              />
            </Field>
            <Field label="Categoría">
              <input
                className="input"
                value={form.category}
                onChange={(event) => update("category", event.target.value)}
                maxLength={80}
              />
            </Field>
            <Field label="Unidad de medida">
              <input
                className="input"
                value={form.uom}
                onChange={(event) => update("uom", event.target.value)}
                maxLength={16}
                placeholder="ud, caja, kg…"
              />
            </Field>
            <Field
              label="Seguimiento"
              hint="Unidad individual crea un código AUR-OBJ por pieza; lote exige batch en cada movimiento"
            >
              <select
                className="select"
                value={form.tracking_mode}
                onChange={(event) => update("tracking_mode", event.target.value)}
              >
                <option value="quantity">Cantidad (masivo)</option>
                <option value="batch">Lote / caducidad</option>
                <option value="unit">Unidad individual</option>
              </select>
            </Field>
            <Field label="Código de barras (EAN)">
              <input
                className="input"
                value={form.barcode}
                onChange={(event) => update("barcode", event.target.value)}
                maxLength={64}
              />
            </Field>
            <Field label="Proveedor">
              <select
                className="select"
                value={form.supplier_id}
                onChange={(event) => update("supplier_id", event.target.value)}
              >
                <option value="">Sin proveedor</option>
                {suppliers.data?.items.map((supplier) => (
                  <option key={supplier.id} value={supplier.id}>
                    {supplier.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Precio de compra (€)" hint="Se usa para valorar las existencias">
              <input
                className="input"
                type="number"
                min="0"
                step="0.01"
                value={form.purchase_price}
                onChange={(event) => update("purchase_price", event.target.value)}
              />
            </Field>
            <Field label="Precio de venta (€)">
              <input
                className="input"
                type="number"
                min="0"
                step="0.01"
                value={form.unit_price}
                onChange={(event) => update("unit_price", event.target.value)}
              />
            </Field>
            <Field label="Stock mínimo" hint="Aviso cuando el físico baja de este valor">
              <input
                className="input"
                type="number"
                min="0"
                step="0.001"
                value={form.min_stock}
                onChange={(event) => update("min_stock", event.target.value)}
              />
            </Field>
            <Field label="Descripción" className="full">
              <textarea
                className="textarea"
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                placeholder="Detalles de manipulación, packaging, observaciones…"
              />
            </Field>
          </div>

          {error ? <div className="form-error" style={{ marginTop: 14 }}>{error}</div> : null}

          <div className="row" style={{ marginTop: 18, justifyContent: "flex-end" }}>
            <Link href="/inventario" className="btn btn-ghost">
              Cancelar
            </Link>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconArrowIn />}
              Crear producto
            </button>
          </div>
        </Card>

        <div className="side-panel">
          <div className="alert">
            <strong>Modelo de identificación</strong>
            <span>
              Cada producto recibe un SKU único e irrepetible. Los palés usan{" "}
              <code className="inline-code">AUR-PAL-000001</code> y cada objeto individual{" "}
              <code className="inline-code">AUR-OBJ-000001</code>.
            </span>
          </div>
          <div className="alert warning">
            <strong>Consejo de operación</strong>
            <span>
              Elige seguimiento por unidad solo para equipos o piezas con número de serie. Para consumibles,
              cantidad o lote son más eficientes.
            </span>
          </div>
        </div>
      </form>
    </>
  );
}
