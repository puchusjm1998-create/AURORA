"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { fmtMinutes, fmtNumber, fmtQty } from "@/lib/format";
import type {
  Location,
  PickingRoute,
  Product,
  PutawaySuggestion,
  Reservation,
  SlottingReport,
  Page,
} from "@/lib/types";
import { LocationPicker, ProductPicker } from "@/components/pickers";
import {
  Badge,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  PageHeader,
  useToast,
} from "@/components/ui";
import { IconRefresh, IconRoute } from "@/components/icons";
import { CalibrationPanel } from "@/components/CalibrationPanel";

function recommendationTone(recommendation: string): string {
  if (recommendation.startsWith("Liberar")) return "warning";
  if (recommendation.startsWith("Mantener")) return "success";
  return "info";
}

export default function OptimizationPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [calibrationToken, setCalibrationToken] = useState(0);
  const [measuredSeconds, setMeasuredSeconds] = useState("");
  const [savingSample, setSavingSample] = useState(false);

  const [product, setProduct] = useState<Product | null>(null);
  const [pallets, setPallets] = useState("1");
  const [putaway, setPutaway] = useState<PutawaySuggestion | null>(null);
  const [putawayError, setPutawayError] = useState<string | null>(null);
  const [putawayLoading, setPutawayLoading] = useState(false);

  const [mode, setMode] = useState<"reference" | "locations">("reference");
  const [reference, setReference] = useState("");
  const [stops, setStops] = useState<Location[]>([]);
  const [route, setRoute] = useState<PickingRoute | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [returnToDispatch, setReturnToDispatch] = useState(true);

  const [days, setDays] = useState(30);
  const slotting = useApi<SlottingReport>(`/api/v1/optimization/slotting?days=${days}&limit=25`, [days]);
  const reservations = useApi<Page<Reservation>>(
    "/api/v1/reservations?status=active&limit=100",
  );

  const references = useMemo(
    () => Array.from(new Set((reservations.data?.items ?? []).map((item) => item.reference))),
    [reservations.data],
  );

  async function suggest() {
    if (!product) {
      setPutawayError("Seleccione un producto.");
      return;
    }
    setPutawayLoading(true);
    setPutawayError(null);
    try {
      const data = await api<PutawaySuggestion>(
        `/api/v1/optimization/putaway?product_id=${product.id}&pallets=${Number(pallets) || 1}`,
      );
      setPutaway(data);
    } catch (err) {
      setPutawayError(errorMessage(err));
    } finally {
      setPutawayLoading(false);
    }
  }

  async function registerTimeStudy() {
    if (!route || route.stops.length === 0) return;
    const seconds = Number(measuredSeconds);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      toast.error("Tiempo no válido", "Indique los segundos cronometrados para esta ruta.");
      return;
    }
    setSavingSample(true);
    try {
      await api("/api/v1/optimization/time-studies", {
        method: "POST",
        body: {
          location_ids: route.stops.map((stop) => stop.location_id),
          measured_seconds: Math.round(seconds),
          notes: `Cronometraje de ruta de ${route.stops.length} parada(s)`,
        },
      });
      toast.success("Tiempo registrado", "Ya puede ajustar la calibración con las muestras.");
      setMeasuredSeconds("");
      setCalibrationToken((current) => current + 1);
    } catch (err) {
      toast.error("No se pudo registrar", errorMessage(err));
    } finally {
      setSavingSample(false);
    }
  }

  async function calculateRoute() {
    const body =
      mode === "reference"
        ? { reservation_reference: reference.trim(), return_to_dispatch: returnToDispatch }
        : { location_ids: stops.map((stop) => stop.id), return_to_dispatch: returnToDispatch };
    if (mode === "reference" && !reference.trim()) {
      setRouteError("Indique la referencia de una reserva activa.");
      return;
    }
    if (mode === "locations" && stops.length === 0) {
      setRouteError("Añada al menos una ubicación.");
      return;
    }
    setRouteLoading(true);
    setRouteError(null);
    try {
      const data = await api<PickingRoute>("/api/v1/optimization/picking-route", {
        method: "POST",
        body,
      });
      setRoute(data);
    } catch (err) {
      setRouteError(errorMessage(err));
    } finally {
      setRouteLoading(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Planificación"
        title="Optimización de ubicaciones y rutas"
        subtitle="Sugerencias calculadas con datos reales del almacén. Nada se mueve ni se reserva automáticamente: usted decide y ejecuta el movimiento."
        actions={
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              slotting.reload();
              reservations.reload();
            }}
            disabled={slotting.loading}
          >
            <IconRefresh /> Actualizar
          </button>
        }
      />

      <div style={{ marginBottom: 18 }}>
        <CalibrationPanel
          refreshToken={calibrationToken}
          onChanged={() => setCalibrationToken((current) => current + 1)}
        />
      </div>

      <section className="card" style={{ marginBottom: 18 }}>
        <div className="card-body">
          <div className="eyebrow">Sugerencia de ubicación</div>
          <h2 className="strong" style={{ marginTop: 4, fontSize: 17 }}>
            Dónde colocar una entrada
          </h2>
          <p className="small text-muted">
            Prioriza consolidar el mismo producto, aprovechar huecos y acercar la alta rotación al
            muelle, penalizando niveles altos.
          </p>
          <div className="row" style={{ marginTop: 12, alignItems: "flex-end" }}>
            <div style={{ flex: "1 1 320px" }}>
              <Field label="Producto">
                <ProductPicker value={product?.id ?? null} onChange={setProduct} />
              </Field>
            </div>
            <Field label="Palés previstos">
              <input
                className="input"
                type="number"
                min="1"
                max="200"
                value={pallets}
                onChange={(event) => setPallets(event.target.value)}
                style={{ width: 110 }}
              />
            </Field>
            <button type="button" className="btn btn-primary" onClick={suggest} disabled={putawayLoading}>
              {putawayLoading ? <span className="spinner" /> : <IconRoute />} Calcular
            </button>
          </div>
          {putawayError ? <div className="form-error" style={{ marginTop: 10 }}>{putawayError}</div> : null}

          {putaway ? (
            <div style={{ marginTop: 14 }}>
              <div className="row">
                <strong>{putaway.product_name}</strong>
                <span className="mono tiny text-muted">{putaway.product_sku}</span>
                {putaway.fast_mover ? (
                  <Badge tone="info">Alta rotación · {putaway.moves} salidas</Badge>
                ) : (
                  <Badge tone="neutral">Baja rotación</Badge>
                )}
                {!putaway.fits ? (
                  <Badge tone="warning">Ninguna posición admite {putaway.pallets} palés</Badge>
                ) : null}
              </div>
              {putaway.candidates.length === 0 ? (
                <EmptyState
                  icon={<IconRoute />}
                  title="Sin ubicaciones candidatas"
                  description="No hay posiciones activas con capacidad libre. Amplíe la capacidad o libere huecos."
                />
              ) : (
                <div className="table-wrap" style={{ marginTop: 10 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Ubicación</th>
                        <th className="num">Libres</th>
                        <th className="num">Distancia</th>
                        <th className="num">Puntuación</th>
                        <th>Motivos</th>
                      </tr>
                    </thead>
                    <tbody>
                      {putaway.candidates.map((candidate, index) => (
                        <tr key={candidate.location_id}>
                          <td className="mono">{index + 1}</td>
                          <td>
                            <Link
                              href={`/ubicacion?code=${encodeURIComponent(candidate.location_code)}`}
                              className="code-chip location"
                            >
                              {candidate.location_code}
                            </Link>
                            {candidate.is_pick_face ? (
                              <div className="tiny text-accent">Cara de picking</div>
                            ) : null}
                          </td>
                          <td className="num">
                            {candidate.free_pallets}/{candidate.capacity_pallets}
                          </td>
                          <td className="num">{fmtNumber(candidate.distance_m, 1)} m</td>
                          <td className="num">
                            <strong>{fmtNumber(candidate.score, 1)}</strong>
                          </td>
                          <td className="small">
                            <ul style={{ margin: 0, paddingLeft: 16 }}>
                              {candidate.reasons.map((reason) => (
                                <li key={reason}>{reason}</li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="tiny text-muted" style={{ marginTop: 8 }}>
                {putaway.note} Supuestos: pasillo {putaway.assumptions.aisle_pitch_m} m, rack{" "}
                {putaway.assumptions.rack_pitch_m} m, posición {putaway.assumptions.position_pitch_m} m.
              </div>
            </div>
          ) : null}
        </div>
      </section>

      <section className="card" style={{ marginBottom: 18 }}>
        <div className="card-body">
          <div className="eyebrow">Ruta de picking</div>
          <h2 className="strong" style={{ marginTop: 4, fontSize: 17 }}>
            Recorrido por pasillos
          </h2>
          <p className="small text-muted">
            Barrido en S: pasillos ascendentes y posiciones alternando sentido para no volver sobre
            los pasos. DISTANCIA y tiempo son estimaciones con el modelo declarado.
          </p>

          <div className="row" style={{ marginTop: 10 }}>
            <button
              type="button"
              className={`btn btn-sm ${mode === "reference" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setMode("reference")}
            >
              Por reserva
            </button>
            <button
              type="button"
              className={`btn btn-sm ${mode === "locations" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setMode("locations")}
            >
              Por ubicaciones
            </button>
            <span className="spacer" />
            <label className="tiny text-muted" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={returnToDispatch}
                onChange={(event) => setReturnToDispatch(event.target.checked)}
              />
              Volver al muelle
            </label>
          </div>

          {mode === "reference" ? (
            <div className="row" style={{ marginTop: 12, alignItems: "flex-end" }}>
              <div style={{ flex: "1 1 320px" }}>
                <Field label="Referencia de reserva activa" hint="Puede escribirla o elegir una de las activas.">
                  <input
                    className="input mono"
                    list="active-reservations"
                    value={reference}
                    onChange={(event) => setReference(event.target.value)}
                    placeholder="PED-2026-0042"
                  />
                  <datalist id="active-reservations">
                    {references.map((item) => (
                      <option key={item} value={item} />
                    ))}
                  </datalist>
                </Field>
              </div>
              <button type="button" className="btn btn-primary" onClick={calculateRoute} disabled={routeLoading}>
                {routeLoading ? <span className="spinner" /> : <IconRoute />} Calcular ruta
              </button>
            </div>
          ) : (
            <div style={{ marginTop: 12 }}>
              <div className="row" style={{ alignItems: "flex-end" }}>
                <div style={{ flex: "1 1 320px" }}>
                  <Field label="Añadir ubicación">
                    <LocationPicker
                      value={null}
                      onChange={(location) => {
                        if (!location) return;
                        setStops((current) =>
                          current.some((item) => item.id === location.id) ? current : [...current, location],
                        );
                      }}
                    />
                  </Field>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={calculateRoute}
                  disabled={routeLoading}
                >
                  {routeLoading ? <span className="spinner" /> : <IconRoute />} Calcular ruta
                </button>
              </div>
              {stops.length > 0 ? (
                <div className="row" style={{ marginTop: 10 }}>
                  {stops.map((stop) => (
                    <button
                      key={stop.id}
                      type="button"
                      className="code-chip location"
                      title="Quitar parada"
                      onClick={() => setStops((current) => current.filter((item) => item.id !== stop.id))}
                    >
                      {stop.full_code} ×
                    </button>
                  ))}
                </div>
              ) : (
                <div className="tiny text-muted" style={{ marginTop: 8 }}>
                  Aún no hay paradas. Use el buscador y pulse una ubicación para añadirla.
                </div>
              )}
            </div>
          )}

          {routeError ? <div className="form-error" style={{ marginTop: 10 }}>{routeError}</div> : null}

          {route ? (
            <div style={{ marginTop: 14 }}>
              <div className="row">
                <Badge tone="info">{route.stops.length} paradas</Badge>
                <span className="count-chip">{fmtNumber(route.total_distance_m, 1)} m</span>
                <span className="count-chip">
                  {fmtMinutes(Math.round(route.total_pick_seconds / 60))} de preparación
                </span>
                <span className="count-chip">
                  {fmtMinutes(Math.round(route.total_estimated_seconds / 60))} estimados
                </span>
                <span className="tiny text-muted">
                  {route.total_walk_seconds} s de marcha · {route.setup_seconds} s de preparación
                </span>
                <span className="tiny text-muted">
                  {route.return_to_dispatch ? "incluye vuelta al muelle" : "sin vuelta al muelle"}
                </span>
              </div>
              {route.stops.length === 0 ? (
                <EmptyState
                  icon={<IconRoute />}
                  title="Ruta vacía"
                  description="La fuente elegida no tiene paradas que preparar."
                />
              ) : (
                <div className="table-wrap" style={{ marginTop: 10 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Ubicación</th>
                        <th>Producto</th>
                        <th className="num">Cantidad</th>
                        <th className="num">Tramo</th>
                        <th className="num">Pick</th>
                      </tr>
                    </thead>
                    <tbody>
                      {route.stops.map((stop) => (
                        <tr key={`${stop.sequence}-${stop.location_id}`}>
                          <td className="mono">{stop.sequence}</td>
                          <td>
                            <Link
                              href={`/ubicacion?code=${encodeURIComponent(stop.location_code)}`}
                              className="code-chip location"
                            >
                              {stop.location_code}
                            </Link>
                          </td>
                          <td className="small">
                            {stop.product_name ? (
                              <>
                                <div className="strong">{stop.product_name}</div>
                                <div className="tiny mono text-muted">
                                  {stop.product_sku}
                                  {stop.pallet_code ? ` · ${stop.pallet_code}` : ""}
                                </div>
                              </>
                            ) : (
                              <span className="text-muted">Parada sin producto asignado</span>
                            )}
                          </td>
                          <td className="num">
                            {stop.quantity ? fmtQty(String(stop.quantity)) : "—"}
                          </td>
                          <td className="num">{fmtNumber(stop.distance_from_previous_m, 1)} m</td>
                          <td className="num">{stop.pick_seconds} s</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="tiny text-muted" style={{ marginTop: 8 }}>
                {route.note}
              </div>
              {can("locations.write") && route.stops.length > 0 ? (
                <div className="row" style={{ marginTop: 12, alignItems: "flex-end", gap: 8 }}>
                  <Field label="Cronometrar esta ruta" hint="Segundos reales desde el muelle hasta volver">
                    <input
                      className="input"
                      type="number"
                      min="1"
                      step="1"
                      value={measuredSeconds}
                      onChange={(event) => setMeasuredSeconds(event.target.value)}
                      placeholder="p. ej. 245"
                      style={{ width: 150 }}
                    />
                  </Field>
                  <button
                    type="button"
                    className="btn"
                    onClick={registerTimeStudy}
                    disabled={savingSample || !measuredSeconds}
                  >
                    {savingSample ? <span className="spinner" /> : <IconRoute />} Registrar tiempo
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      <section className="card">
        <div className="toolbar">
          <strong className="small">Análisis de ubicación (slotting)</strong>
          <select
            className="select"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            aria-label="Periodo"
          >
            <option value={7}>Últimos 7 días</option>
            <option value={30}>Últimos 30 días</option>
            <option value={90}>Últimos 90 días</option>
          </select>
          <span className="spacer" />
          <span className="count-chip">{slotting.data ? `${slotting.data.total} productos` : "—"}</span>
        </div>
        {slotting.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={slotting.error} onRetry={slotting.reload} />
          </div>
        ) : null}
        {slotting.loading && !slotting.data ? <LoadingBlock label="Analizando rotación…" /> : null}
        {slotting.data && slotting.data.items.length === 0 ? (
          <EmptyState
            icon={<IconRoute />}
            title="Sin datos suficientes"
            description="No hay movimientos ni stock en el periodo elegido. Registre recepciones y salidas primero."
          />
        ) : null}
        {slotting.data && slotting.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Producto</th>
                  <th className="num">Salidas</th>
                  <th className="num">Unidades fuera</th>
                  <th className="num">Stock</th>
                  <th className="num">Ubicaciones</th>
                  <th className="num">Al muelle</th>
                  <th>Recomendación</th>
                </tr>
              </thead>
              <tbody>
                {slotting.data.items.map((row) => (
                  <tr key={row.product_id}>
                    <td>
                      <Link href={`/producto?id=${row.product_id}`} className="strong small">
                        {row.product_name}
                      </Link>
                      <div className="tiny mono text-muted">{row.product_sku}</div>
                    </td>
                    <td className="num">{row.moves}</td>
                    <td className="num">{fmtQty(row.units_out)}</td>
                    <td className="num">{fmtQty(row.on_hand)}</td>
                    <td className="num">
                      {row.locations}
                      {row.in_pick_face ? <div className="tiny text-accent">picking</div> : null}
                    </td>
                    <td className="num">
                      {row.nearest_distance_m === null ? "—" : `${fmtNumber(row.nearest_distance_m, 1)} m`}
                    </td>
                    <td className="small">
                      <Badge tone={recommendationTone(row.recommendation) as "info"}>
                        {row.recommendation}
                      </Badge>
                      <div className="tiny text-muted">{row.reason}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {slotting.data ? (
          <div className="tiny text-muted" style={{ padding: "0 16px 14px" }}>
            {slotting.data.note}
          </div>
        ) : null}
      </section>

      <div className="alert" style={{ marginTop: 14 }}>
        <strong>Sugerencias, no automatismos</strong>
        <span>
          Las distancias y tiempos usan un modelo geométrico declarado (pasillo 3 m, rack 6 m,
          posición 1 m, 25 s por parada + 6 s por nivel). Ninguna recomendación mueve stock: use{" "}
          <Link href="/operaciones">Operaciones</Link> para ejecutar el movimiento auditado.
        </span>
      </div>
    </>
  );
}
