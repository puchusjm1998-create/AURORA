"use client";

import type { GeoPoint } from "@/lib/geo";

/**
 * Recorrido GPS en SVG, sin teselas externas ni dependencias de mapas.
 * Se escala a partir de la latitud/longitud de los puntos recibidos.
 */
export function TrackingTrail({
  points,
  height = 190,
  label = "Recorrido GPS del reparto",
}: {
  points: GeoPoint[];
  height?: number;
  label?: string;
}) {
  const valid = points.filter(
    (point) => Number.isFinite(point.latitude) && Number.isFinite(point.longitude),
  );
  if (valid.length === 0) return null;

  const width = 600;
  const pad = 22;
  const lats = valid.map((point) => point.latitude);
  const lons = valid.map((point) => point.longitude);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const spanLat = maxLat - minLat;
  const spanLon = maxLon - minLon;

  const project = (point: GeoPoint) => {
    const x = spanLon === 0 ? width / 2 : pad + ((point.longitude - minLon) / spanLon) * (width - pad * 2);
    const y = spanLat === 0 ? height / 2 : pad + (1 - (point.latitude - minLat) / spanLat) * (height - pad * 2);
    return { x, y };
  };

  const projected = valid.map(project);
  const path = projected.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const first = projected[0];
  const last = projected[projected.length - 1];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      role="img"
      aria-label={`${label}: ${valid.length} posiciones`}
      style={{
        display: "block",
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface-2, rgba(0,0,0,0.03))",
      }}
    >
      <defs>
        <pattern id="trail-grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--border)" strokeWidth="0.5" opacity="0.6" />
        </pattern>
      </defs>
      <rect width={width} height={height} fill="url(#trail-grid)" />
      {valid.length > 1 ? (
        <polyline
          points={path}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ) : null}
      <circle cx={first.x} cy={first.y} r={6} fill="var(--success, #15803d)" stroke="#fff" strokeWidth={2} />
      <circle cx={last.x} cy={last.y} r={7} fill="var(--accent)" stroke="#fff" strokeWidth={2} />
      {valid.length > 1 ? (
        <text x={last.x + 10} y={last.y - 10} fontSize={12} fill="var(--text-muted, #64748b)">
          Última
        </text>
      ) : null}
    </svg>
  );
}
