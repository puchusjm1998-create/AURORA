"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import {
  fmtMoney,
  fmtNumber,
  fmtQty,
  fmtRelative,
  num,
  movementBadge,
  movementDirection,
  movementLabel,
  occupancyTone,
} from "@/lib/format";
import type { DashboardData } from "@/lib/types";
import {
  Badge,
  Card,
  ErrorBlock,
  LoadingBlock,
  PageHeader,
  Stat,
} from "@/components/ui";
import {
  IconAlert,
  IconArrowIn,
  IconArrowOut,
  IconCamera,
  IconChevron,
  IconPallet,
  IconReports,
  IconRefresh,
  IconReserve,
  IconTask,
  IconScan,
  IconWarehouse,
} from "@/components/icons";

export default function DashboardPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<DashboardData>("/api/v1/dashboard");

  const greeting = (() => {
    const hour = Number(
      new Intl.DateTimeFormat("es-ES", { hour: "2-digit", hour12: false, timeZone: "Europe/Madrid" }).format(
        new Date(),
      ),
    );
    if (hour < 6) return "Buenas noches";
    if (hour < 14) return "Buenos días";
    if (hour < 21) return "Buenas tardes";
    return "Buenas noches";
  })();

  return (
    <>
      <PageHeader
        eyebrow="Centro de control"
        title={`${greeting}, ${user?.full_name?.split(" ")[0] ?? "equipo"}`}
        subtitle="Estado operativo del almacén en tiempo real. Datos en UTC, mostrados en hora de Madrid."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={reload} disabled={loading}>
              <IconRefresh /> Actualizar
            </button>
            <Link href="/escaner" className="btn btn-ghost">
              <IconCamera /> Escanear
            </Link>
            <Link href="/tareas" className="btn btn-ghost">
              <IconTask /> Tareas
            </Link>
            <Link href="/reservas" className="btn btn-ghost">
              <IconReserve /> Reservas
            </Link>
            <Link href="/operaciones" className="btn btn-primary">
              <IconScan /> Nueva operación
            </Link>
          </>
        }
      />

      {data && data.kpis.critical_incidents > 0 ? (
        <div className="alert danger" style={{ marginBottom: 16 }}>
          <strong>
            {data.kpis.critical_incidents}{" "}
            {data.kpis.critical_incidents === 1 ? "incidencia crítica abierta" : "incidencias críticas abiertas"}
          </strong>
          <span>
            Requieren atención del encargado antes de seguir operando.{" "}
            <Link href="/incidencias" className="text-accent">
              Revisar incidencias
            </Link>
            {data.kpis.open_incidents > data.kpis.critical_incidents
              ? ` · ${data.kpis.open_incidents} abiertas en total`
              : ""}
          </span>
        </div>
      ) : null}

      {error ? <ErrorBlock message={error} onRetry={reload} /> : null}
      {loading && !data ? <LoadingBlock label="Calculando indicadores…" /> : null}

      {data ? (
        <div className="stack" style={{ gap: 18 }}>
          <div className="grid grid-4">
            <Stat
              label="Existencias totales"
              value={fmtNumber(data.kpis.total_units, 0)}
              meta={<span>unidades físicas · {data.kpis.active_products} referencias activas</span>}
              accent
            />
            <Stat
              label="Valor del stock"
              value={fmtMoney(data.kpis.stock_value)}
              meta={<span>valorado a precio de adquisición</span>}
            />
            <Stat
              label="Ocupación"
              value={`${data.kpis.occupancy_pct}%`}
              meta={
                <>
                  <span className="badge no-dot" style={{ padding: 0, background: "none", color: `var(--${occupancyTone(data.kpis.occupancy_pct)})` }}>
                    {data.kpis.locations} ubicaciones
                  </span>
                </>
              }
            />
            <Stat
              label="Palés"
              value={data.kpis.pallets_stored + data.kpis.pallets_open}
              meta={<span>{data.kpis.pallets_stored} precintados · {data.kpis.pallets_open} abiertos</span>}
            />
          </div>

          <div className="grid grid-4">
            <Stat
              label="Movimientos hoy"
              value={data.kpis.movements_today}
              meta={
                <span>
                  <span className="text-success">↑ {data.kpis.receptions_today} entradas</span> ·{" "}
                  <span className="text-warning">↓ {data.kpis.shipments_today} salidas</span>
                </span>
              }
            />
            <Stat
              label="Stock bajo mínimo"
              value={data.kpis.low_stock_products}
              meta={<span>{data.kpis.low_stock_products ? "requiere reposición" : "todo por encima del mínimo"}</span>}
            />
            <Stat
              label="Facturas pendientes"
              value={data.kpis.pending_invoices}
              meta={<span>por revisar o conciliar</span>}
            />
            <Stat
              label="Equipo activo"
              value={data.kpis.workers_active}
              meta={<span>{data.kpis.movements_draft} movimientos en borrador</span>}
            />
          </div>

          <div className="grid grid-5">
            <Stat
              label="Tareas abiertas"
              value={data.kpis.open_tasks}
              meta={
                <span>
                  {data.kpis.overdue_tasks ? (
                    <span className="text-danger">{data.kpis.overdue_tasks} vencidas</span>
                  ) : (
                    "sin vencimientos"
                  )}
                </span>
              }
            />
            <Stat
              label="Reservas activas"
              value={data.kpis.active_reservations}
              meta={<span>pedidos con stock comprometido</span>}
            />
            <Stat
              label="Unidades reservadas"
              value={fmtNumber(data.kpis.reserved_units, 0)}
              meta={<span>no disponibles para otras salidas</span>}
            />
            <Stat
              label="Incidencias abiertas"
              value={data.kpis.open_incidents}
              meta={
                <Link href="/incidencias" className="text-accent">
                  {data.kpis.critical_incidents} de alta severidad
                </Link>
              }
            />
            <Stat
              label="Disponible real"
              value={fmtNumber(num(data.kpis.total_units) - num(data.kpis.reserved_units), 0)}
              meta={<span>físico menos reservado</span>}
            />
          </div>

          <div className="split">
            <div className="stack">
              <Card
                title="Actividad reciente"
                subtitle="Últimos movimientos registrados en el libro de stock"
                actions={
                  <Link href="/movimientos" className="btn btn-sm btn-ghost">
                    Ver historial <IconChevron />
                  </Link>
                }
                flush
              >
                {data.recent_activity.length === 0 ? (
                  <div className="empty">
                    <IconArrowIn />
                    <strong>Todavía no hay movimientos</strong>
                    <p>Registra una recepción para empezar a construir el histórico del almacén.</p>
                    <Link href="/operaciones" className="btn btn-sm btn-primary">
                      Registrar entrada
                    </Link>
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Referencia</th>
                          <th>Tipo</th>
                          <th>Producto</th>
                          <th className="num">Cantidad</th>
                          <th>Recorrido</th>
                          <th>Cuándo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.recent_activity.map((item) => {
                          const dir = movementDirection(item.type);
                          return (
                            <tr key={item.id}>
                              <td className="mono">{item.reference}</td>
                              <td>
                                <Badge tone={item.status === "confirmed" ? "success" : item.status === "draft" ? "warning" : "danger"}>
                                  {movementLabel(item.type)}
                                </Badge>
                              </td>
                              <td className="strong">{item.product}</td>
                              <td className="num">
                                <span className={dir === "in" ? "text-success" : dir === "out" ? "text-warning" : ""}>
                                  {dir === "in" ? "+" : dir === "out" ? "−" : ""}
                                  {fmtQty(item.quantity, item.uom)}
                                </span>
                              </td>
                              <td className="mono small text-muted">
                                {item.from_location ?? "—"} → {item.to_location ?? "—"}
                              </td>
                              <td className="small text-muted nowrap">{fmtRelative(item.created_at)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              <Card title="Ocupación por almacén" subtitle="Ubicaciones con existencias frente al total">
                <div className="stack" style={{ gap: 16 }}>
                  {data.warehouse_occupancy.length === 0 ? (
                    <div className="empty">
                      <IconWarehouse />
                      <strong>Sin almacenes configurados</strong>
                      <p>Crea un almacén y sus ubicaciones para empezar a operar.</p>
                    </div>
                  ) : (
                    data.warehouse_occupancy.map((warehouse) => {
                      const pct = warehouse.locations
                        ? Math.round((warehouse.occupied / warehouse.locations) * 100)
                        : 0;
                      return (
                        <div className="bar-row" key={warehouse.warehouse_code}>
                          <div className="bar-top">
                            <span>
                              <span className="mono text-accent">{warehouse.warehouse_code}</span>{" "}
                              {warehouse.warehouse_name}
                            </span>
                            <span className="text-muted">
                              {warehouse.occupied}/{warehouse.locations} · {pct}%
                            </span>
                          </div>
                          <div className={`progress${pct >= 90 ? " warn" : ""}`}>
                            <i style={{ width: `${Math.min(pct, 100)}%` }} />
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </Card>
            </div>

            <div className="side-panel">
              <Card title="Accesos rápidos">
                <div className="stack" style={{ gap: 8 }}>
                  <Link href="/operaciones?tab=recepcion" className="nav-item" style={{ padding: "12px" }}>
                    <IconArrowIn /> Registrar recepción
                  </Link>
                  <Link href="/operaciones?tab=expedicion" className="nav-item" style={{ padding: "12px" }}>
                    <IconArrowOut /> Registrar expedición
                  </Link>
                  <Link href="/pales" className="nav-item" style={{ padding: "12px" }}>
                    <IconPallet /> Construir un palé
                  </Link>
                  <Link href="/informes" className="nav-item" style={{ padding: "12px" }}>
                    <IconReports /> Informes y valoración
                  </Link>
                </div>
              </Card>

              <Card
                title="Reposición necesaria"
                subtitle="Referencias por debajo del mínimo"
                actions={
                  data.low_stock.length ? (
                    <Badge tone="warning">{data.low_stock.length}</Badge>
                  ) : (
                    <Badge tone="success">OK</Badge>
                  )
                }
              >
                {data.low_stock.length === 0 ? (
                  <p className="small text-muted">
                    Ninguna referencia activa está por debajo de su stock mínimo.
                  </p>
                ) : (
                  <div className="stack" style={{ gap: 12 }}>
                    {data.low_stock.map((item) => {
                      const pct = Math.min(100, Math.round((Number(item.on_hand) / Math.max(Number(item.min_stock), 0.001)) * 100));
                      return (
                        <div key={item.sku} className="bar-row">
                          <div className="bar-top">
                            <span className="truncate" style={{ maxWidth: "65%" }}>{item.name}</span>
                            <span className="text-warning">
                              {fmtNumber(item.on_hand, 0)} / {fmtNumber(item.min_stock, 0)}
                            </span>
                          </div>
                          <div className="progress warn">
                            <i style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Card>

              <div className="alert">
                <strong>Fase 1 operativa</strong>
                <span>
                  Inventario, trazabilidad QR, palés, movimientos y auditoría están activos. Consulta el estado
                  de las siguientes fases en <Link href="/sistema" className="text-accent">Sistema</Link>.
                </span>
              </div>

              {data.top_products.length ? (
                <Card title="Mayor valor en stock">
                  <div className="stack" style={{ gap: 10 }}>
                    {data.top_products.map((item) => (
                      <div key={item.sku} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                        <div style={{ minWidth: 0 }}>
                          <div className="small truncate">{item.name}</div>
                          <div className="tiny mono text-muted">{item.sku}</div>
                        </div>
                        <span className="small nowrap">{fmtMoney(item.value)}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              ) : null}

              <div className="alert warning">
                <strong><IconAlert width={14} height={14} style={{ display: "inline", verticalAlign: "-2px" }} /> AURORA Voice</strong>
                <span>
                  La asistente por voz (Fase 5) todavía no está operativa; no se muestran funciones simuladas.
                </span>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
