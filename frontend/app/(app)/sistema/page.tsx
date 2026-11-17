"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
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

            <Card title="Pendiente de fases posteriores" subtitle="No se presentan como funcionalidades disponibles">
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
                      <td><Badge tone="warning">Fase 4</Badge></td>
                      <td className="small text-muted">Bucket, región y credenciales IAM</td>
                    </tr>
                    <tr>
                      <td>OCR de facturas</td>
                      <td><Badge tone="warning">Sin proveedor</Badge></td>
                      <td className="small text-muted">API key del proveedor OCR</td>
                    </tr>
                    <tr>
                      <td>AURORA Voice (STT/TTS/LLM)</td>
                      <td><Badge tone="warning">Fase 5</Badge></td>
                      <td className="small text-muted">Proveedor intercambiable + voz española</td>
                    </tr>
                    <tr>
                      <td>Telefonía</td>
                      <td><Badge tone="warning">Fase 8</Badge></td>
                      <td className="small text-muted">SIP trunk o API de llamadas</td>
                    </tr>
                    <tr>
                      <td>Redis / Celery</td>
                      <td><Badge tone="warning">Fase 4+</Badge></td>
                      <td className="small text-muted"><code className="inline-code">REDIS_URL</code></td>
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
                Prometheus; puede protegerse con <code>METRICS_TOKEN</code>. Las trazas siguen pendientes.
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
                La interfaz de conversación, el reconocimiento y la síntesis de voz se incorporarán en la Fase 5
                con el proveedor que se configure. No hay micrófono simulado en esta entrega.
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
