"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { fmtDateTime, fmtNumber, palletStatusMeta } from "@/lib/format";
import type { Location, Page, Pallet, StockLevel } from "@/lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  PageHeader,
  QrPreview,
  Stat,
} from "@/components/ui";
import {
  IconBox,
  IconPallet,
  IconPin,
  IconPrint,
  IconWarehouse,
} from "@/components/icons";

function LocationDetail() {
  const params = useSearchParams();
  const code = params.get("code");
  const id = params.get("id");
  const { can } = useAuth();

  const location = useApi<Location>(
    code ? `/api/v1/locations/by-code/${encodeURIComponent(code)}` : id ? `/api/v1/locations/${id}` : null,
    [code, id],
  );
  const locationId = location.data?.id;
  const levels = useApi<Page<StockLevel>>(
    locationId ? withQuery("/api/v1/stock/levels", { location_id: locationId, limit: 100 }) : null,
    [locationId],
  );
  const pallets = useApi<Page<Pallet>>(
    locationId ? withQuery("/api/v1/pallets", { location_id: locationId, limit: 50 }) : null,
    [locationId],
  );

  if (!code && !id) {
    return (
      <EmptyState
        icon={<IconPin />}
        title="Ubicación no indicada"
        description="Selecciona una ubicación desde el mapa del almacén o escanea su etiqueta QR."
        action={
          <Link href="/almacenes" className="btn btn-primary btn-sm">
            Ver almacenes
          </Link>
        }
      />
    );
  }
  if (location.error) return <ErrorBlock message={location.error} onRetry={location.reload} />;
  if (location.loading || !location.data) return <LoadingBlock label="Cargando ubicación…" />;

  const data = location.data;
  const payload = `aurora://location/${data.full_code}`;
  const occupancy = data.capacity_pallets
    ? Math.round((data.occupied_pallets / data.capacity_pallets) * 100)
    : 0;

  return (
    <>
      <PageHeader
        eyebrow="Ubicación física"
        title={data.full_code}
        subtitle={data.label || `${data.warehouse_code} · Pasillo ${data.aisle}, estantería ${data.rack}, nivel ${data.level}, posición ${data.position}`}
        actions={
          <>
            <Link href={`/almacen?id=${data.warehouse_id}`} className="btn btn-ghost">
              <IconWarehouse /> Almacén
            </Link>
            <Link href={`/etiquetas?kind=location&ids=${data.id}`} className="btn btn-primary">
              <IconPrint /> Etiqueta QR
            </Link>
          </>
        }
      />

      <div className="grid" style={{ gap: 18 }}>
        <div className="detail-hero">
          <div className="title-row">
            <div style={{ flex: 1, minWidth: 240 }}>
              <div className="row" style={{ gap: 8, marginBottom: 6 }}>
                <span className="code-chip location">{data.full_code}</span>
                {data.is_pick_face ? <Badge tone="accent">Picking</Badge> : null}
                {data.is_active ? <Badge tone="success">Activa</Badge> : <Badge tone="danger">Inactiva</Badge>}
              </div>
              <h1>{data.label || "Posición de almacenamiento"}</h1>
              <div className="detail-meta" style={{ marginTop: 8 }}>
                <span>Almacén: <b>{data.warehouse_code}</b></span>
                <span>Pasillo: <b>{data.aisle}</b></span>
                <span>Estantería: <b>{data.rack}</b></span>
                <span>Nivel: <b>{data.level}</b></span>
                <span>Posición: <b>{data.position}</b></span>
              </div>
            </div>
            <QrPreview payload={payload} code={data.full_code} />
          </div>
        </div>

        <div className="grid grid-4">
          <Stat label="Palés" value={`${data.occupied_pallets}/${data.capacity_pallets}`} meta={<span>ocupación {occupancy}%</span>} accent />
          <Stat label="Unidades" value={fmtNumber(data.occupied_units, 3)} meta={<span>stock físico total</span>} />
          <Stat label="Referencias" value={levels.data?.items.length ?? 0} meta={<span>productos distintos</span>} />
          <Stat
            label="Tipo"
            value={data.is_pick_face ? "Picking" : "Reserva"}
            meta={<span>{data.is_pick_face ? "acceso preferente" : "almacenamiento masivo"}</span>}
          />
        </div>

        <div className="split">
          <div className="stack">
            <Card
              title="Contenido de la ubicación"
              subtitle="Existencias físicas y reservadas por referencia"
              flush
              actions={<Badge tone="accent">{levels.data?.total ?? 0} posiciones</Badge>}
            >
              {levels.loading && !levels.data ? <LoadingBlock /> : null}
              {levels.data && levels.data.items.length === 0 ? (
                <EmptyState
                  icon={<IconBox />}
                  title="Ubicación vacía"
                  description={
                    can("movements.write")
                      ? "No hay mercancía almacenada aquí. Puedes registrar una recepción con esta ubicación como destino."
                      : "No hay mercancía almacenada en esta posición."
                  }
                  action={
                    can("movements.write") ? (
                      <Link href="/operaciones?tab=recepcion" className="btn btn-sm btn-primary">
                        Registrar entrada
                      </Link>
                    ) : undefined
                  }
                />
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Producto</th>
                        <th className="num">Físico</th>
                        <th className="num">Reservado</th>
                        <th className="num">Disponible</th>
                        <th>Palé</th>
                        <th>Actualizado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {levels.data?.items.map((level) => (
                        <tr key={level.id}>
                          <td>
                            <Link href={`/producto?id=${level.product_id}`} className="strong small">
                              {level.product_name}
                            </Link>
                            <div className="tiny mono text-muted">
                              {level.product_sku} · {level.uom}
                            </div>
                          </td>
                          <td className="num">{fmtNumber(level.quantity, 3)}</td>
                          <td className="num text-muted">{fmtNumber(level.reserved_quantity, 3)}</td>
                          <td className="num">{fmtNumber(level.available_quantity, 3)}</td>
                          <td>
                            {level.pallet_code ? (
                              <Link href={`/pale?id=${level.pallet_id}`} className="code-chip">
                                {level.pallet_code}
                              </Link>
                            ) : (
                              <span className="small text-muted">Estantería</span>
                            )}
                          </td>
                          <td className="small text-muted nowrap">{fmtDateTime(level.updated_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            <Card title="Palés en la ubicación" flush>
              {pallets.loading && !pallets.data ? <LoadingBlock /> : null}
              {pallets.data && pallets.data.items.length === 0 ? (
                <EmptyState icon={<IconPallet />} title="Sin palés" description="No hay palés almacenados en esta posición." />
              ) : (
                <div className="table-wrap">
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th>Código</th>
                        <th>Estado</th>
                        <th className="num">Referencias</th>
                        <th className="num">Unidades</th>
                        <th className="actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {pallets.data?.items.map((pallet) => {
                        const meta = palletStatusMeta[pallet.status];
                        return (
                          <tr key={pallet.id}>
                            <td className="mono">{pallet.code}</td>
                            <td><Badge tone={meta.tone as "success"}>{meta.label}</Badge></td>
                            <td className="num">{pallet.item_count}</td>
                            <td className="num">{fmtNumber(pallet.total_units, 3)}</td>
                            <td className="actions">
                              <Link href={`/pale?id=${pallet.id}`} className="btn btn-sm btn-ghost">
                                Abrir
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
          </div>

          <div className="side-panel">
            <Card title="Etiqueta de la posición">
              <p className="small text-muted" style={{ marginBottom: 10 }}>
                Imprime y coloca el QR en la estantería. Escanearlo abre esta misma ficha.
              </p>
              <div className="row">
                <Link href={`/etiquetas?kind=location&ids=${data.id}`} className="btn btn-block">
                  <IconPrint /> Imprimir etiqueta
                </Link>
              </div>
            </Card>
            <div className="alert">
              <strong>Jerarquía completa</strong>
              <span>
                Almacén {data.warehouse_code} → Pasillo {data.aisle} → Estantería {data.rack} → Nivel{" "}
                {data.level} → Posición {data.position}. La mercancía de esta ubicación solo puede moverse con
                un movimiento registrado y confirmado.
              </span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

export default function LocationPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <LocationDetail />
    </Suspense>
  );
}
