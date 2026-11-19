"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { haversineMeters, requestScreenWakeLock } from "@/lib/geo";
import { useApi } from "@/lib/useApi";
import {
  deliveryStatusMeta,
  fmtDateTime,
  fmtQty,
} from "@/lib/format";
import type {
  Delivery,
  DeliverySignature,
  DeliveryTrackingSummary,
  Page,
} from "@/lib/types";
import { TrackingTrail } from "@/components/TrackingTrail";
import {
  Badge,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  PageHeader,
  useToast,
} from "@/components/ui";
import {
  IconCheck,
  IconPin,
  IconRefresh,
  IconTrash,
  IconTruck,
} from "@/components/icons";

type GeoState = "idle" | "on" | "error" | "unsupported";

function ageLabel(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "sin datos";
  if (seconds < 60) return `hace ${seconds} s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)} min`;
  return `hace ${Math.round(seconds / 3600)} h`;
}

export default function MyDeliveryPage() {
  const toast = useToast();
  const deliveries = useApi<Page<Delivery>>("/api/v1/deliveries/mine");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = deliveries.data?.items.find((item) => item.id === selectedId) ?? null;

  const tracking = useApi<DeliveryTrackingSummary>(
    selected ? `/api/v1/deliveries/${selected.id}/tracking` : null,
    [selected?.id],
  );
  const signature = useApi<DeliverySignature>(
    selected?.has_signature ? `/api/v1/deliveries/${selected.id}/signature` : null,
    [selected?.id, selected?.has_signature],
  );

  const [geoState, setGeoState] = useState<GeoState>("idle");
  const [position, setPosition] = useState<{
    latitude: number;
    longitude: number;
    accuracy: number | null;
    speed: number | null;
    heading: number | null;
    at: number;
  } | null>(null);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [sent, setSent] = useState(0);
  const [wakeLockActive, setWakeLockActive] = useState(false);
  const watchId = useRef<number | null>(null);
  const lastSentAt = useRef(0);
  const lastSentPosition = useRef<{ latitude: number; longitude: number } | null>(null);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const selectedIdRef = useRef<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawing = useRef(false);
  const [hasInk, setHasInk] = useState(false);
  const [signerName, setSignerName] = useState("");
  const [signerDocument, setSignerDocument] = useState("");
  const [signatureError, setSignatureError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    if (!deliveries.data) return;
    if (selectedId && deliveries.data.items.some((item) => item.id === selectedId)) return;
    const active = deliveries.data.items.find((item) => item.status === "in_transit");
    setSelectedId((active ?? deliveries.data.items[0])?.id ?? null);
  }, [deliveries.data, selectedId]);

  const acquireWakeLock = useCallback(async () => {
    if (wakeLockRef.current && !wakeLockRef.current.released) return;
    const lock = await requestScreenWakeLock();
    if (lock) {
      lock.onrelease = () => {
        wakeLockRef.current = null;
        setWakeLockActive(false);
      };
    }
    wakeLockRef.current = lock;
    setWakeLockActive(lock !== null);
  }, []);

  const stopTracking = useCallback(() => {
    if (watchId.current !== null && typeof navigator !== "undefined") {
      navigator.geolocation.clearWatch(watchId.current);
      watchId.current = null;
    }
    if (wakeLockRef.current) {
      void wakeLockRef.current.release();
      wakeLockRef.current = null;
    }
    setWakeLockActive(false);
    setGeoState("idle");
  }, []);

  useEffect(() => {
    selectedIdRef.current = selectedId;
    if (watchId.current !== null) stopTracking();
    setSent(0);
    setGeoError(null);
    setPosition(null);
  }, [selectedId, stopTracking]);

  useEffect(() => () => stopTracking(), [stopTracking]);

  useEffect(() => {
    if (geoState !== "on") return;
    const onVisibility = () => {
      if (document.visibilityState === "visible") void acquireWakeLock();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [geoState, acquireWakeLock]);

  useEffect(() => {
    if (!selected || selected.has_signature) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "#111827";
    context.lineWidth = 3;
    context.lineCap = "round";
    context.lineJoin = "round";
    setHasInk(false);
  }, [selected?.id, selected?.has_signature]);

  async function sendPosition(
    latitude: number,
    longitude: number,
    accuracy: number | null,
    speed: number | null,
    heading: number | null,
  ) {
    const deliveryId = selectedIdRef.current;
    if (!deliveryId) return;
    try {
      await api(`/api/v1/deliveries/${deliveryId}/tracking`, {
        method: "POST",
        body: {
          latitude,
          longitude,
          accuracy_m: accuracy,
          speed_mps: speed,
          heading_deg: heading,
        },
      });
      setSent((value) => value + 1);
      setGeoError(null);
      tracking.reload();
    } catch (err) {
      setGeoError(errorMessage(err));
    }
  }

  function startTracking() {
    if (!selected) return;
    if (!("geolocation" in navigator)) {
      setGeoState("unsupported");
      setGeoError("Este navegador no dispone de geolocalización.");
      return;
    }
    if (watchId.current !== null) return;
    lastSentAt.current = 0;
    lastSentPosition.current = null;
    setGeoState("on");
    setGeoError(null);
    void acquireWakeLock();
    watchId.current = navigator.geolocation.watchPosition(
      (positionData) => {
        const { latitude, longitude, accuracy, speed, heading } = positionData.coords;
        const cleanAccuracy = Number.isFinite(accuracy) ? accuracy : null;
        const cleanSpeed = Number.isFinite(speed) ? speed : null;
        const cleanHeading = Number.isFinite(heading) ? heading : null;
        setPosition({
          latitude,
          longitude,
          accuracy: cleanAccuracy,
          speed: cleanSpeed,
          heading: cleanHeading,
          at: Date.now(),
        });
        const now = Date.now();
        const moved = lastSentPosition.current
          ? haversineMeters(lastSentPosition.current, { latitude, longitude })
          : Number.POSITIVE_INFINITY;
        // Más frecuencia al moverse; una señal cada 45 s si está parado.
        const interval = moved >= 25 ? 12000 : 45000;
        if (now - lastSentAt.current < interval) return;
        lastSentAt.current = now;
        lastSentPosition.current = { latitude, longitude };
        void sendPosition(latitude, longitude, cleanAccuracy, cleanSpeed, cleanHeading);
      },
      (error) => {
        setGeoState("error");
        setGeoError(
          error.code === error.PERMISSION_DENIED
            ? "Permiso de ubicación denegado. Actívelo en el navegador para compartir la ruta."
            : "No se pudo obtener la ubicación GPS. Compruebe la señal y el permiso.",
        );
        if (watchId.current !== null) {
          navigator.geolocation.clearWatch(watchId.current);
          watchId.current = null;
        }
        if (wakeLockRef.current) {
          void wakeLockRef.current.release();
          wakeLockRef.current = null;
        }
        setWakeLockActive(false);
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    );
  }

  function canvasPoint(event: React.PointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * canvas.width,
      y: ((event.clientY - rect.top) / rect.height) * canvas.height,
    };
  }

  function startStroke(event: React.PointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    canvas.setPointerCapture(event.pointerId);
    drawing.current = true;
    const point = canvasPoint(event);
    context.beginPath();
    context.moveTo(point.x, point.y);
    setHasInk(true);
  }

  function drawStroke(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    const context = canvasRef.current?.getContext("2d");
    if (!context) return;
    const point = canvasPoint(event);
    context.lineTo(point.x, point.y);
    context.stroke();
  }

  function endStroke(event: React.PointerEvent<HTMLCanvasElement>) {
    drawing.current = false;
    canvasRef.current?.releasePointerCapture(event.pointerId);
  }

  function clearSignature() {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    setHasInk(false);
    setSignatureError(null);
  }

  async function signDelivery(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    if (!hasInk) {
      setSignatureError("Capture la firma del receptor antes de continuar.");
      return;
    }
    if (signerName.trim().length < 2) {
      setSignatureError("Indique el nombre de la persona que firma.");
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    setSigning(true);
    setSignatureError(null);
    try {
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/png"),
      );
      if (!blob) throw new Error("No se pudo generar la imagen de la firma.");
      const form = new FormData();
      form.append("file", blob, "firma.png");
      form.append("signer_name", signerName.trim());
      form.append("signer_document", signerDocument.trim());
      form.append("mark_delivered", "true");
      if (position) {
        form.append("latitude", String(position.latitude));
        form.append("longitude", String(position.longitude));
      }
      await api(`/api/v1/deliveries/${selected.id}/signature`, {
        method: "POST",
        body: form,
      });
      toast.success("Entrega firmada", `${selected.reference} queda como entregado.`);
      stopTracking();
      deliveries.reload();
      signature.reload();
      tracking.reload();
    } catch (err) {
      setSignatureError(errorMessage(err));
      toast.error("No se pudo firmar la entrega", errorMessage(err));
    } finally {
      setSigning(false);
    }
  }

  const inTransit = selected?.status === "in_transit";
  const last = tracking.data?.last ?? null;
  const statusMeta = selected
    ? deliveryStatusMeta[selected.status] ?? { tone: "neutral", label: selected.status }
    : null;

  return (
    <>
      <PageHeader
        eyebrow="Conductor"
        title="Mi reparto"
        subtitle="Comparta la posición GPS durante el transporte y capture la firma del receptor. Cada envío queda como evidencia inmutable y auditada."
        actions={
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              deliveries.reload();
              tracking.reload();
              signature.reload();
            }}
          >
            <IconRefresh /> Actualizar
          </button>
        }
      />

      {deliveries.error ? (
        <ErrorBlock message={deliveries.error} onRetry={deliveries.reload} />
      ) : null}
      {deliveries.loading && !deliveries.data ? (
        <LoadingBlock label="Cargando sus repartos…" />
      ) : null}
      {deliveries.data && deliveries.data.items.length === 0 ? (
        <EmptyState
          icon={<IconTruck />}
          title="Sin repartos asignados"
          description="Cuando un responsable le asigne un reparto cargado o en tránsito, aparecerá aquí."
        />
      ) : null}

      {deliveries.data && deliveries.data.items.length > 0 ? (
        <>
          <section className="card" style={{ marginBottom: 16 }}>
            <div className="toolbar">
              <strong className="small">Repartos asignados</strong>
              <span className="spacer" />
              <select
                className="select"
                value={selectedId ?? ""}
                onChange={(event) => setSelectedId(event.target.value)}
                aria-label="Reparto"
              >
                {deliveries.data.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.reference} · {item.destination_name}
                  </option>
                ))}
              </select>
            </div>
          </section>

          {selected ? (
            <>
              <div className="grid grid-4" style={{ marginBottom: 18 }}>
                <div className="kpi kpi-accent">
                  <span className="kpi-label">Estado</span>
                  <div className="kpi-value">
                    <Badge tone={statusMeta?.tone as "info"}>{statusMeta?.label}</Badge>
                  </div>
                  <span className="kpi-meta">{selected.reference}</span>
                </div>
                <div className="kpi">
                  <span className="kpi-label">Destino</span>
                  <div className="strong small" style={{ marginTop: 6 }}>
                    {selected.destination_name}
                  </div>
                  <span className="kpi-meta">{selected.destination_address || "Sin dirección"}</span>
                </div>
                <div className="kpi">
                  <span className="kpi-label">Carga</span>
                  <div className="kpi-value">{selected.pallets.length} palés</div>
                  <span className="kpi-meta">{fmtQty(selected.total_units)} unidades</span>
                </div>
                <div className="kpi">
                  <span className="kpi-label">Vehículo</span>
                  <div className="kpi-value" style={{ fontSize: 20 }}>
                    {selected.vehicle_plate ?? "—"}
                  </div>
                  <span className="kpi-meta">
                    {selected.departed_at
                      ? `salió ${fmtDateTime(selected.departed_at)}`
                      : "transporte no iniciado"}
                  </span>
                </div>
              </div>

              <section className="card" style={{ marginBottom: 18 }}>
                <div className="card-body">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <div>
                      <div className="eyebrow">
                        <IconPin /> Seguimiento GPS
                      </div>
                      <div className="small text-muted">
                        El navegador envía una posición cada 12 segundos en movimiento y cada 45
                        segundos parado, mientras el reparto está en tránsito. Mantiene la pantalla
                        activa si el navegador lo permite; requiere permiso de ubicación y HTTPS.
                      </div>
                    </div>
                    <div className="row">
                      {inTransit && geoState !== "on" ? (
                        <button type="button" className="btn btn-primary" onClick={startTracking}>
                          <IconPin /> Compartir ubicación
                        </button>
                      ) : null}
                      {geoState === "on" ? (
                        <button type="button" className="btn btn-ghost" onClick={stopTracking}>
                          Detener GPS
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {geoError ? (
                    <div className="alert warning" style={{ marginTop: 12 }}>
                      <strong>GPS no disponible</strong>
                      <span>{geoError}</span>
                    </div>
                  ) : null}
                  {geoState === "on" ? (
                    <div className="alert info" style={{ marginTop: 12 }}>
                      <strong>Compartiendo ubicación</strong>
                      <span>
                        {sent} posiciones enviadas
                        {position ? ` · última ${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}` : ""}
                        {position?.accuracy ? ` · ±${Math.round(position.accuracy)} m` : ""}
                        {wakeLockActive ? " · pantalla activa" : ""}
                      </span>
                    </div>
                  ) : null}

                  <div className="grid grid-2" style={{ gap: 18, marginTop: 14 }}>
                    <div>
                      <div className="tiny text-muted">Última posición registrada</div>
                      {last ? (
                        <>
                          <div className="small strong">
                            {last.latitude.toFixed(6)}, {last.longitude.toFixed(6)}
                          </div>
                          <div className="tiny text-muted">
                            {fmtDateTime(last.recorded_at)} ·{" "}
                            {ageLabel(tracking.data?.stale_seconds)} ·{" "}
                            {tracking.data ? `${(tracking.data.distance_m / 1000).toFixed(2)} km` : "—"}
                          </div>
                          <a
                            className="btn btn-sm btn-ghost"
                            style={{ marginTop: 6 }}
                            href={`https://www.openstreetmap.org/?mlat=${last.latitude}&mlon=${last.longitude}#map=17/${last.latitude}/${last.longitude}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Abrir en OpenStreetMap
                          </a>
                        </>
                      ) : (
                        <div className="small text-muted">Todavía no hay posiciones enviadas.</div>
                      )}
                    </div>
                    <div>
                      <div className="tiny text-muted">Indicaciones</div>
                      <a
                        className="small text-accent"
                        href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(
                          selected.destination_address || selected.destination_name,
                        )}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Buscar el destino en OpenStreetMap
                      </a>
                      {!inTransit ? (
                        <div className="small text-muted" style={{ marginTop: 6 }}>
                          El GPS solo se envía cuando el reparto está en tránsito.
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {tracking.data && tracking.data.points.length > 0 ? (
                    <div style={{ marginTop: 16 }}>
                      <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
                        <span className="tiny text-muted">
                          Recorrido · {tracking.data.points.length} posiciones
                        </span>
                        <span className="tiny text-muted">
                          {(tracking.data.distance_m / 1000).toFixed(2)} km acumulados
                        </span>
                      </div>
                      <TrackingTrail points={tracking.data.points} />
                    </div>
                  ) : null}
                  {tracking.error ? <ErrorBlock message={tracking.error} onRetry={tracking.reload} /> : null}
                </div>
              </section>

              <section className="card">
                <div className="card-body">
                  <div className="eyebrow">Firma del receptor</div>
                  {selected.has_signature && signature.data ? (
                    <>
                      <div className="alert success" style={{ marginTop: 10 }}>
                        <strong>Entrega firmada por {signature.data.signer_name}</strong>
                        <span>
                          {fmtDateTime(signature.data.signed_at)} · SHA-256{" "}
                          <span className="mono">{signature.data.sha256.slice(0, 20)}…</span>
                        </span>
                      </div>
                      <img
                        src={signature.data.image_url}
                        alt={`Firma de ${signature.data.signer_name}`}
                        style={{
                          display: "block",
                          width: "100%",
                          maxWidth: 460,
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          background: "#fff",
                        }}
                      />
                    </>
                  ) : !inTransit ? (
                    <p className="small text-muted" style={{ marginTop: 8 }}>
                      La firma se captura cuando el reparto está en tránsito. Estado actual:{" "}
                      {statusMeta?.label}.
                    </p>
                  ) : (
                    <form onSubmit={signDelivery} style={{ marginTop: 10 }}>
                      {signatureError ? (
                        <div className="alert danger" style={{ marginBottom: 12 }}>
                          <span>{signatureError}</span>
                        </div>
                      ) : null}
                      <div className="form-grid">
                        <Field label="Nombre de quien firma" required>
                          <input
                            className="input"
                            value={signerName}
                            onChange={(event) => setSignerName(event.target.value)}
                            placeholder="Nombre y apellidos"
                            maxLength={120}
                          />
                        </Field>
                        <Field label="DNI / documento" hint="Opcional">
                          <input
                            className="input"
                            value={signerDocument}
                            onChange={(event) => setSignerDocument(event.target.value)}
                            maxLength={32}
                          />
                        </Field>
                      </div>
                      <div className="tiny text-muted" style={{ margin: "12px 0 6px" }}>
                        Firme dentro del recuadro con el dedo o el ratón.
                      </div>
                      <canvas
                        ref={canvasRef}
                        width={720}
                        height={220}
                        onPointerDown={startStroke}
                        onPointerMove={drawStroke}
                        onPointerUp={endStroke}
                        onPointerCancel={endStroke}
                        style={{
                          display: "block",
                          width: "100%",
                          maxWidth: 720,
                          height: "auto",
                          touchAction: "none",
                          cursor: "crosshair",
                          border: "1px dashed var(--border-strong, var(--border))",
                          borderRadius: 8,
                          background: "#fff",
                        }}
                      />
                      <div className="row" style={{ marginTop: 12 }}>
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={clearSignature}
                          disabled={signing}
                        >
                          <IconTrash /> Borrar firma
                        </button>
                        <span className="spacer" />
                        <button type="submit" className="btn btn-primary" disabled={signing}>
                          {signing ? <span className="spinner" /> : <IconCheck />} Firmar y entregar
                        </button>
                      </div>
                      <p className="tiny text-muted" style={{ marginTop: 8 }}>
                        Al firmar se marca el reparto como entregado y se guarda la imagen con su
                        SHA-256. La firma no se puede editar ni borrar.
                      </p>
                    </form>
                  )}
                </div>
              </section>

              <div className="alert" style={{ marginTop: 14 }}>
                <strong>Evidencia real, no una firma dibujada</strong>
                <span>
                  La imagen se sube al servidor, se verifica como PNG y se almacena con hash. El
                  punto GPS de la firma se registra solo si el navegador lo entrega. Si no hay
                  permiso de ubicación, la firma sigue siendo válida pero sin coordenada asociada.
                </span>
              </div>
            </>
          ) : null}
        </>
      ) : null}
    </>
  );
}
