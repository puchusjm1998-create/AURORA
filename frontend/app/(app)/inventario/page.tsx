"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { downloadFile, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import {
  fmtMoney,
  fmtNumber,
  fmtQty,
  trackingLabel,
} from "@/lib/format";
import type { Page, Product } from "@/lib/types";
import {
  Badge,
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  PageHeader,
  Pagination,
  SearchInput,
  useToast,
} from "@/components/ui";
import {
  IconBox,
  IconDownload,
  IconPlus,
  IconQr,
  IconRefresh,
} from "@/components/icons";

interface Facets {
  categories: { name: string; count: number }[];
  suppliers: { id: string; name: string; count: number }[];
}

const LIMIT = 25;

export default function InventoryPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [supplier, setSupplier] = useState("");
  const [tracking, setTracking] = useState("");
  const [invoice, setInvoice] = useState("");
  const [locationCode, setLocationCode] = useState("");
  const [lowStock, setLowStock] = useState(false);
  const [offset, setOffset] = useState(0);
  const debounced = useDebounced(search, 280);

  const facets = useApi<Facets>("/api/v1/products/facets");
  const query = useMemo(
    () =>
      withQuery("/api/v1/products", {
        search: debounced || null,
        category: category || null,
        supplier_id: supplier || null,
        tracking_mode: tracking || null,
        invoice_number: invoice.trim() || null,
        location_code: locationCode.trim() || null,
        low_stock: lowStock ? true : null,
        limit: LIMIT,
        offset,
      }),
    [debounced, category, supplier, tracking, invoice, locationCode, lowStock, offset],
  );
  const { data, error, loading, reload } = useApi<Page<Product>>(query);

  const resetTo = (fn: () => void) => {
    fn();
    setOffset(0);
  };

  return (
    <>
      <PageHeader
        eyebrow="Inventario"
        title="Existencias en tiempo real"
        subtitle="Físico, reservado, disponible y en tránsito por referencia. Cada movimiento queda auditado."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={reload} disabled={loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("reports.export") ? (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={async () => {
                  try {
                    await downloadFile("/api/v1/reports/inventory.csv", "aurora-inventario.csv");
                    toast.success("Informe generado", "Descarga del inventario en CSV completada.");
                  } catch (err) {
                    toast.error("No se pudo exportar", errorMessage(err));
                  }
                }}
              >
                <IconDownload /> CSV
              </button>
            ) : null}
            {can("inventory.write") ? (
              <Link href="/productos/nuevo" className="btn btn-primary">
                <IconPlus /> Nuevo producto
              </Link>
            ) : null}
          </>
        }
      />

      <section className="card">
        <div className="toolbar">
          <SearchInput
            value={search}
            onChange={(value) => resetTo(() => setSearch(value))}
            placeholder="Buscar por SKU, nombre, referencia, barras o proveedor…"
          />
          <select
            className="select"
            value={category}
            onChange={(event) => resetTo(() => setCategory(event.target.value))}
            aria-label="Filtrar por categoría"
          >
            <option value="">Todas las categorías</option>
            {facets.data?.categories.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name} ({item.count})
              </option>
            ))}
          </select>
          <select
            className="select"
            value={supplier}
            onChange={(event) => resetTo(() => setSupplier(event.target.value))}
            aria-label="Filtrar por proveedor"
          >
            <option value="">Todos los proveedores</option>
            {facets.data?.suppliers.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={tracking}
            onChange={(event) => resetTo(() => setTracking(event.target.value))}
            aria-label="Filtrar por seguimiento"
          >
            <option value="">Cualquier seguimiento</option>
            <option value="quantity">Cantidad</option>
            <option value="batch">Lote</option>
            <option value="unit">Unidad individual</option>
          </select>
          <input
            className="input"
            value={invoice}
            onChange={(event) => resetTo(() => setInvoice(event.target.value))}
            placeholder="Nº de factura"
            aria-label="Buscar por número de factura"
            style={{ width: 150 }}
          />
          <input
            className="input mono"
            value={locationCode}
            onChange={(event) => resetTo(() => setLocationCode(event.target.value.toUpperCase()))}
            placeholder="ALM-01-P04-EB-N02-POS03"
            aria-label="Buscar por ubicación exacta"
            style={{ width: 230 }}
          />
          <label className="check" style={{ marginLeft: 2 }}>
            <input
              type="checkbox"
              checked={lowStock}
              onChange={(event) => resetTo(() => setLowStock(event.target.checked))}
            />
            Bajo mínimo
          </label>
          <span className="spacer" />
          <span className="count-chip">{data ? `${data.total} referencias` : "—"}</span>
        </div>

        {error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={error} onRetry={reload} />
          </div>
        ) : null}

        {loading && !data ? <LoadingBlock label="Consultando inventario…" /> : null}

        {data && data.items.length === 0 ? (
          <EmptyState
            icon={<IconBox />}
            title="Sin resultados"
            description="No hay productos que coincidan con los filtros. Ajusta la búsqueda o crea una nueva referencia."
            action={
              can("inventory.write") ? (
                <Link href="/productos/nuevo" className="btn btn-sm btn-primary">
                  <IconPlus /> Crear producto
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
                    <th>SKU</th>
                    <th>Producto</th>
                    <th>Proveedor</th>
                    <th className="num">Físico</th>
                    <th className="num">Reservado</th>
                    <th className="num">Disponible</th>
                    <th className="num">En tránsito</th>
                    <th className="num">Valor</th>
                    <th>Ubicaciones</th>
                    <th className="actions">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((product) => (
                    <tr key={product.id}>
                      <td className="mono">
                        <Link href={`/producto?id=${product.id}`} className="text-accent">
                          {product.sku}
                        </Link>
                      </td>
                      <td>
                        <div className="strong">{product.name}</div>
                        <div className="small text-muted">
                          {product.category} · {trackingLabel[product.tracking_mode]} · {product.uom}
                          {product.manufacturer_ref ? ` · Ref. ${product.manufacturer_ref}` : ""}
                        </div>
                      </td>
                      <td className="small">{product.supplier?.name ?? "—"}</td>
                      <td className="num">{fmtNumber(product.stock.on_hand, 3)}</td>
                      <td className="num text-muted">{fmtNumber(product.stock.reserved, 3)}</td>
                      <td className="num">
                        <Badge tone={Number(product.stock.available) > 0 ? "success" : "danger"} dot={false}>
                          {fmtNumber(product.stock.available, 3)}
                        </Badge>
                      </td>
                      <td className="num text-muted">{fmtNumber(product.stock.in_transit, 3)}</td>
                      <td className="num">{fmtMoney(product.stock.value)}</td>
                      <td className="num">{product.stock.locations}</td>
                      <td className="actions">
                        <div className="row tight" style={{ justifyContent: "flex-end" }}>
                          <Link href={`/producto?id=${product.id}`} className="btn btn-sm btn-ghost">
                            Ver
                          </Link>
                          <Link
                            href={`/etiquetas?kind=product&ids=${product.id}`}
                            className="btn btn-sm btn-ghost"
                            title="Imprimir etiqueta QR"
                            aria-label={`Imprimir etiqueta de ${product.sku}`}
                          >
                            <IconQr />
                          </Link>
                        </div>
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

      <p className="hint" style={{ marginTop: 12 }}>
        {data
          ? `Mostrando ${fmtQty(data.items.reduce((acc, item) => acc + Number(item.stock.on_hand), 0))} unidades físicas en esta página.`
          : "Cargando indicadores de existencias…"}
      </p>
    </>
  );
}
