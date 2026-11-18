"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { QueueStatus, StorageStatus } from "@/lib/types";
import { fmtDateTime, warehouseTimeNow } from "@/lib/format";
import { Badge, Card, PageHeader } from "@/components/ui";
import {
  IconAlert,
  IconCheck,
  IconInfo,
  IconMic,
  IconShield,
  IconWarehouse,
} from "@/components/icons";

export default function SystemPage() {
  const { system, user } = useAuth();
  const storage = useApi<StorageStatus>("/api/v1/system/storage");
  const queue = useApi<QueueStatus>("/api/v1/system/queue");
  const [warehouseTime, setWarehouseTime] = useState("—");
  const [checkedAt, setCheckedAt] = useState("—");

  useEffect(() => {
    const tick = () => {
      setWarehouseTime(warehouseTimeNow());
      setCheckedAt(fmtDateTime(new Date().toISOString()));
    };
    tick();
    const timer = window.setInterval(tick, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <>
      <PageHeader
        eyebrow="Transparencia"
        title="Estado del sistema"
        subtitle="Qué está realmente operativo, qué depende de proveedores externos y qué queda por construir."
      />

      <div className="grid" style={{ gap: 18 }}>
        <div className="grid grid-4">
          <div className="kpi">
            <span className="kpi-label">Entorno</span>
            <span className="kpi-value" style={{ fontSize: 22 }}>{system?.environment ?? "—"}</span>
            <span className="kpi-meta">{system?.demo_mode ? "Datos de demostración" : "Datos reales"}</span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Versión</span>
            <span className="kpi-value" style={{ fontSize: 22 }}>{system?.version ?? "—"}</span>
            <span className="kpi-meta">{system?.name}</span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Hora del almacén</span>
            <span className="kpi-value" style={{ fontSize: 22 }} suppressHydrationWarning>{warehouseTime}</span>
            <span className="kpi-meta">{system?.warehouse_timezone}</span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Su nivel</span>
            <span className="kpi-value" style={{ fontSize: 22 }}>{user?.role_level ?? "—"}</span>
            <span className="kpi-meta">{user?.role_name}</span>
          </div>
        </div>

        <div className="grid grid-2">
          <Card
            title="Almacenamiento documental"
            subtitle={storage.data ? `${storage.data.backend.toUpperCase()} · prefijo ${storage.data.prefix || "—"}` : "Comprobando…"}
            actions={
              <button className="btn btn-sm btn-ghost" onClick={storage.reload} disabled={storage.loading}>
                Reintentar
              </button>
            }
          >
            {storage.error ? (
              <div className="alert danger">{storage.error}</div>
            ) : (
              <div className="stack" style={{ gap: 8 }}>
                <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                  <span className="small">Estado</span>
                  <Badge tone={storage.data?.reachable ? "success" : "warning"}>
                    {storage.data?.reachable ? "Bucket accesible" : "Sin bucket remoto"}
                  </Badge>
                </div>
                <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                  <span className="small">Bucket</span>
                  <code className="inline-code">{storage.data?.bucket || "local"}</code>
                </div>
                <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                  <span className="small">Endpoint</span>
                  <span className="tiny text-muted">{storage.data?.endpoint || "filesystem local"}</span>
                </div>
                {storage.data?.error && <p className="hint">{storage.data.error}</p>}
                <p className="hint">
                  Las firmas, fotos y PDF de factura se guardan con SHA-256. Con <code>STORAGE_BACKEND=s3</code> se
                  suben a S3 (AWS, MinIO o Ceph) y la descarga se cachea en el servidor.
                </p>
              </div>
            )}
          </Card>

          <Card
            title="Cola de tareas"
            subtitle={queue.data ? `Celery · ${queue.data.broker}` : "Comprobando…"}
            actions={
              <button className="btn btn-sm btn-ghost" onClick={queue.reload} disabled={queue.loading}>
                Reintentar
              </button>
            }
          >
            {queue.error ? (
              <div className="alert danger">{queue.error}</div>
            ) : (
              <div className="stack" style={{ gap: 8 }}>
                <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                  <span className="small">Broker Redis</span>
                  <Badge tone={queue.data?.broker_available ? "success" : "warning"}>
                    {queue.data?.broker_available ? "Conectado" : "No disponible"}
                  </Badge>
                </div>
                <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                  <span className="small">Worker</span>
                  <Badge tone={queue.data?.worker_online ? "success" : "warning"}>
                    {queue.data?.worker_online ? "En línea" : "Sin worker"}
                  </Badge>
                </div>
                <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                  <span className="small">Modo</span>
                  <span className="tiny text-muted">{queue.data?.eager ? "eager (pruebas)" : "asíncrono"}</span>
                </div>
                <p className="hint">{queue.data?.message}</p>
              </div>
            )}
          </Card>
        </div>

        <div className="split">
          <div className="stack">
            <Card title="Funcionalidades operativas" subtitle={system?.phase}>
              <div className="stack" style={{ gap: 8 }}>
                {(system?.implemented ?? []).map((item) => (
                  <div key={item} className="row" style={{ gap: 8, alignItems: "flex-start" }}>
                    <span style={{ color: "var(--success)", marginTop: 2 }}><IconCheck width={15} height={15} /></span>
                    <span className="small text-soft">{item}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card title="Límites externos y dependencias" subtitle="Lo que no puede probarse sin infraestructura o credenciales del cliente">
              <div className="stack" style={{ gap: 8 }}>
                {(system?.pending ?? []).map((item) => (
                  <div key={item} className="row" style={{ gap: 8, alignItems: "flex-start" }}>
                    <span style={{ color: "var(--warning)", marginTop: 2 }}><IconAlert width={15} height={15} /></span>
                    <span className="small text-soft">{item}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card title="Integraciones externas y credenciales necesarias">
              <div className="table-wrap">
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Servicio</th>
                      <th>Estado</th>
                      <th>Qué necesita</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>PostgreSQL</td>
                      <td><Badge tone={system?.environment === "development" ? "warning" : "success"}>{system?.environment === "development" ? "SQLite local" : "Activo"}</Badge></td>
                      <td className="small text-muted"><code className="inline-code">DATABASE_URL</code></td>
                    </tr>
                    <tr>
                      <td>Almacenamiento documental S3</td>
                      <td><Badge tone={storage.data?.reachable ? "success" : storage.data?.backend === "s3" ? "warning" : "info"}>{storage.data?.reachable ? "Activo" : storage.data?.backend === "s3" ? "Sin conexión" : "Local"}</Badge></td>
                      <td className="small text-muted"><code className="inline-code">S3_BUCKET</code>, región y credenciales IAM</td>
                    </tr>
                    <tr>
                      <td>OCR de facturas</td>
                      <td><Badge tone="success">Local (ONNX)</Badge></td>
                      <td className="small text-muted">Sin API externa; RapidOCR dentro del servidor</td>
                    </tr>
                    <tr>
                      <td>AURORA Voice (TTS neuronal)</td>
                      <td><Badge tone="success">Activo</Badge></td>
                      <td className="small text-muted"><code className="inline-code">VOICE_TTS_PROVIDER</code> (piper/edge/openai/browser)</td>
                    </tr>
                    <tr>
                      <td>Telefonía</td>
                      <td><Badge tone="info">Handoff</Badge></td>
                      <td className="small text-muted">SIP trunk o API de llamadas para marcación automática</td>
                    </tr>
                    <tr>
                      <td>Redis / Celery</td>
                      <td><Badge tone={queue.data?.broker_available ? "success" : "warning"}>{queue.data?.broker_available ? "Activo" : "No disponible"}</Badge></td>
                      <td className="small text-muted"><code className="inline-code">REDIS_URL</code> + worker</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <div className="side-panel">
            <Card title="Documentación técnica">
              <div className="stack" style={{ gap: 8 }}>
                <a href="/api/docs" target="_blank" rel="noreferrer" className="btn btn-block">
                  <IconInfo /> API interactiva (OpenAPI)
                </a>
                <a href="/api/openapi.json" target="_blank" rel="noreferrer" className="btn btn-block btn-ghost">
                  Esquema OpenAPI JSON
                </a>
                <a href="/healthz" target="_blank" rel="noreferrer" className="btn btn-block btn-ghost">
                  Estado del servicio
                </a>
                <a href="/metrics" target="_blank" rel="noreferrer" className="btn btn-block btn-ghost">
                  Métricas Prometheus
                </a>
              </div>
              <p className="hint" style={{ marginTop: 10 }}>
                La documentación de API se genera automáticamente a partir del código y se actualiza con cada
                despliegue. <code>/metrics</code> expone latencias, errores, base de datos y operación en formato
                Prometheus; puede protegerse con <code>METRICS_TOKEN</code>. Las trazas OpenTelemetry se
                exportan por OTLP o consola con <code>AURORA_TRACING_ENABLED=true</code>.
              </p>
            </Card>

            <Card title="Modelo de autorización">
              <div className="stack" style={{ gap: 10 }}>
                {[
                  ["Nivel 1", "Administrador principal", "Acceso completo"],
                  ["Nivel 2", "Responsable de logística", "Operaciones y facturas"],
                  ["Nivel 3", "Encargado", "Recepción, expedición y equipos"],
                  ["Nivel 4", "Trabajador", "Tareas, escaneo y movimientos"],
                  ["Nivel 5", "Auditor", "Solo lectura y auditoría"],
                ].map(([level, role, note]) => (
                  <div key={level} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                    <span className="small"><b>{level}</b> · {role}</span>
                    <span className="tiny text-muted">{note}</span>
                  </div>
                ))}
              </div>
            </Card>

            <div className="alert warning">
              <strong><IconMic width={14} height={14} style={{ display: "inline", verticalAlign: "-2px" }} /> Voz femenina española</strong>
              <span>
                La síntesis neuronal funciona en <Link href="/voz">AURORA Voice</Link> con el proveedor configurado
                (<code>edge</code> no necesita clave; <code>openai</code> requiere <code>VOICE_TTS_API_KEY</code>).
                Si el proveedor no está disponible, el navegador sintetiza en local. El reconocimiento de voz
                sigue siendo el del navegador: no se envía audio a AURORA.
              </span>
            </div>

            <div className="alert">
              <strong><IconWarehouse width={14} height={14} style={{ display: "inline", verticalAlign: "-2px" }} /> Infraestructura</strong>
              <span>
                Preparada para Docker y cloud europea. Consulte <code className="inline-code">docs/DEPLOYMENT.md</code>{" "}
                para el despliegue con PostgreSQL y HTTPS.
              </span>
            </div>

            <Card title="Sesión actual">
              <div className="small text-muted">
                {user?.email}
                <br />
                Última comprobación: <span suppressHydrationWarning>{checkedAt}</span>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <Link href="/perfil" className="btn btn-sm btn-ghost">
                  <IconShield /> Seguridad
                </Link>
                <Link href="/auditoria" className="btn btn-sm btn-ghost">
                  Auditoría
                </Link>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
