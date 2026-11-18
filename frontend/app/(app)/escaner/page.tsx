"use client";

import Link from "next/link";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { ScanResult } from "@/lib/types";
import { QrScanner } from "@/components/QrScanner";
import {
  Badge,
  Card,
  Field,
  PageHeader,
  Tabs,
  useToast,
} from "@/components/ui";
import {
  IconArrowIn,
  IconBox,
  IconPallet,
  IconPin,
  IconQr,
  IconRefresh,
  IconScan,
  IconUsers,
} from "@/components/icons";

interface Scan {
  result: ScanResult;
  at: string;
}

const KIND_META: Record<ScanResult["kind"], { label: string; tone: "accent" | "success" | "info" }> = {
  product: { label: "Producto", tone: "accent" },
  pallet: { label: "Palé", tone: "success" },
  unit: { label: "Unidad individual", tone: "info" },
  location: { label: "Ubicación", tone: "accent" },
  employee: { label: "Trabajador", tone: "info" },
};

export default function ScannerPage() {
  const toast = useToast();
  const [tab, setTab] = useState<"camara" | "manual">("camara");
  const [manual, setManual] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<ScanResult | null>(null);
  const [history, setHistory] = useState<Scan[]>([]);

  async function resolve(code: string) {
    const value = code.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<ScanResult>("/api/v1/scan/resolve", { query: { code: value } });
      setCurrent(result);
      setHistory((items) => [{ result, at: new Date().toISOString() }, ...items].slice(0, 6));
      setManual("");
      toast.success("Código reconocido", `${KIND_META[result.kind].label} · ${result.code}`);
    } catch (err) {
      setCurrent(null);
      setError(errorMessage(err));
      toast.error("Código no reconocido", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Trazabilidad QR"
        title="Escáner AURORA"
        subtitle="Identifica productos, palés, objetos unitarios, ubicaciones y trabajadores. El procesamiento de imagen ocurre en tu dispositivo."
        actions={
          <Link href="/etiquetas" className="btn btn-ghost">
            <IconQr /> Generar etiquetas
          </Link>
        }
      />

      <div className="split">
        <div className="stack">
          <section className="card">
            <Tabs
              tabs={[
                { value: "camara", label: "Cámara" },
                { value: "manual", label: "Código manual" },
              ]}
              value={tab}
              onChange={(value) => setTab(value as "camara" | "manual")}
            />
            <div className="card-body">
              {tab === "camara" ? (
                <QrScanner onResult={resolve} paused={busy} />
              ) : (
                <form
                  className="stack"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void resolve(manual);
                  }}
                >
                  <Field
                    label="Código o contenido QR"
                    hint="Ejemplos: aurora://pallet/AUR-PAL-000001 · AUR-OBJ-000004 · ALM-01-P01-EA-N01-POS01"
                  >
                    <input
                      className="input input-lg mono"
                      value={manual}
                      onChange={(event) => setManual(event.target.value)}
                      placeholder="aurora://product/AUR-SKU-000001"
                      autoFocus
                    />
                  </Field>
                  <button type="submit" className="btn btn-primary btn-lg" disabled={busy || !manual.trim()}>
                    {busy ? <span className="spinner" /> : <IconScan />} Resolver código
                  </button>
                  <p className="hint">
                    También puedes escribir directamente el SKU, el código de palé, el código de objeto o el
                    código completo de ubicación.
                  </p>
                </form>
              )}

              {error ? <div className="form-error" style={{ marginTop: 12 }}>{error}</div> : null}
            </div>
          </section>

          {current ? (
            <div className="scan-result">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <Badge tone={KIND_META[current.kind].tone}>{KIND_META[current.kind].label}</Badge>
                <span className="code small">{current.code}</span>
              </div>
              <div>
                <div className="strong" style={{ fontSize: 18 }}>
                  {current.title}
                </div>
                <div className="small text-muted">{current.subtitle}</div>
              </div>
              {Object.keys(current.extra ?? {}).length ? (
                <div className="row" style={{ gap: 6 }}>
                  {Object.entries(current.extra).map(([key, value]) =>
                    value === null || value === undefined || value === "" ? null : (
                      <span className="tag-pill" key={key}>
                        {key}: <b>{String(value)}</b>
                      </span>
                    ),
                  )}
                </div>
              ) : null}
              <div className="row">
                <Link href={current.href} className="btn btn-primary">
                  <IconArrowIn /> Abrir ficha
                </Link>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => {
                    setCurrent(null);
                    setError(null);
                  }}
                >
                  <IconRefresh /> Escanear otro
                </button>
              </div>
            </div>
          ) : null}

          {history.length ? (
            <Card title="Últimas lecturas" subtitle="Solo durante esta sesión">
              <div className="stack" style={{ gap: 8 }}>
                {history.map((item, index) => (
                  <button
                    key={`${item.result.code}-${index}`}
                    type="button"
                    className="nav-item"
                    style={{ width: "100%", justifyContent: "space-between" }}
                    onClick={() => setCurrent(item.result)}
                  >
                    <span className="row" style={{ gap: 8 }}>
                      {item.result.kind === "pallet" ? (
                        <IconPallet />
                      ) : item.result.kind === "location" ? (
                        <IconPin />
                      ) : item.result.kind === "employee" ? (
                        <IconUsers />
                      ) : (
                        <IconBox />
                      )}
                      <span>
                        <span className="small strong">{item.result.title}</span>
                        <span className="tiny mono text-muted" style={{ display: "block" }}>
                          {item.result.code}
                        </span>
                      </span>
                    </span>
                    <span className="tiny text-muted">{fmtRelative(item.at)}</span>
                  </button>
                ))}
              </div>
            </Card>
          ) : null}
        </div>

        <div className="side-panel">
          <Card title="Qué puedes escanear">
            <div className="stack" style={{ gap: 12 }}>
              <div className="row" style={{ gap: 10 }}>
                <IconBox />
                <div>
                  <div className="small strong">Producto</div>
                  <div className="tiny text-muted">
                    <span className="mono">aurora://product/AUR-SKU-…</span> abre ficha y localización.
                  </div>
                </div>
              </div>
              <div className="row" style={{ gap: 10 }}>
                <IconPallet />
                <div>
                  <div className="small strong">Palé</div>
                  <div className="tiny text-muted">
                    <span className="mono">aurora://pallet/AUR-PAL-…</span> muestra contenido y estado.
                  </div>
                </div>
              </div>
              <div className="row" style={{ gap: 10 }}>
                <IconPin />
                <div>
                  <div className="small strong">Ubicación</div>
                  <div className="tiny text-muted">
                    <span className="mono">aurora://location/ALM-01-…</span> consulta ocupación y contenido.
                  </div>
                </div>
              </div>
              <div className="row" style={{ gap: 10 }}>
                <IconQr />
                <div>
                  <div className="small strong">Objeto unitario</div>
                  <div className="tiny text-muted">
                    <span className="mono">aurora://unit/AUR-OBJ-…</span> identifica una pieza concreta.
                  </div>
                </div>
              </div>
            </div>
          </Card>

          <div className="alert warning">
            <strong>Privacidad</strong>
            <span>
              La cámara solo se activa al pulsar el botón. El vídeo nunca sale del dispositivo: únicamente se
              envía el código leído. No se realiza reconocimiento biométrico.
            </span>
          </div>

          <Card title="Etiquetas">
            <p className="small text-muted" style={{ marginBottom: 10 }}>
              Genera hojas imprimibles en A4 para ubicaciones, palés, productos y objetos.
            </p>
            <Link href="/etiquetas" className="btn btn-block">
              <IconQr /> Abrir generador
            </Link>
          </Card>
        </div>
      </div>
    </>
  );
}
