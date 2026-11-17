"use client";

import { useState } from "react";
import { downloadFile, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { fmtDateTime, fmtMoney, fmtNumber } from "@/lib/format";
import type { ValuationSummary } from "@/lib/types";
import {
  Badge,
  Card,
  ErrorBlock,
  Field,
  LoadingBlock,
  PageHeader,
  Stat,
  useToast,
} from "@/components/ui";
import { IconDownload, IconReports, IconRefresh } from "@/components/icons";

export default function ReportsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const summary = useApi<ValuationSummary>("/api/v1/reports/summary");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const totalPurchase = summary.data?.categories.reduce((acc, item) => acc + Number(item.purchase_value), 0) ?? 0;
  const totalSale = summary.data?.categories.reduce((acc, item) => acc + Number(item.sale_value), 0) ?? 0;
  const totalUnits = summary.data?.categories.reduce((acc, item) => acc + Number(item.units), 0) ?? 0;

  async function exportCsv(kind: "inventory" | "movements") {
    setBusy(kind);
    try {
      const params = new URLSearchParams();
      if (kind === "movements") {
        if (dateFrom) params.set("date_from", new Date(`${dateFrom}T00:00:00`).toISOString());
        if (dateTo) params.set("date_to", new Date(`${dateTo}T23:59:59`).toISOString());
      }
      const suffix = params.toString() ? `?${params.toString()}` : "";
      await downloadFile(`/api/v1/reports/${kind}.csv${suffix}`, `aurora-${kind}.csv`);
      toast.success("Informe descargado", "Archivo CSV compatible con Excel (UTF-8).");
    } catch (err) {
      toast.error("No se pudo generar el informe", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Análisis"
        title="Informes y valoración"
        subtitle="Datos reales del inventario, exportables para contabilidad y control de gestión."
        actions={
          <button type="button" className="btn btn-ghost" onClick={summary.reload} disabled={summary.loading}>
            <IconRefresh /> Actualizar
          </button>
        }
      />

      {!can("reports.read") ? (
        <div className="alert warning">
          <strong>Acceso restringido</strong>
          <span>Su perfil no dispone de permiso para consultar informes.</span>
        </div>
      ) : null}

      {summary.error ? <ErrorBlock message={summary.error} onRetry={summary.reload} /> : null}
      {summary.loading && !summary.data ? <LoadingBlock label="Calculando valoración…" /> : null}

      {summary.data ? (
        <div className="stack" style={{ gap: 18 }}>
          <div className="grid grid-4">
            <Stat label="Valor a coste" value={fmtMoney(totalPurchase)} meta={<span>precio de adquisición</span>} accent />
            <Stat label="Valor de venta" value={fmtMoney(totalSale)} meta={<span>precio unitario</span>} />
            <Stat label="Unidades" value={fmtNumber(totalUnits, 0)} meta={<span>stock físico total</span>} />
            <Stat
              label="Categorías"
              value={summary.data.categories.length}
              meta={<span>actualizado {fmtDateTime(summary.data.generated_at)}</span>}
            />
          </div>

          <div className="split">
            <Card title="Valoración por categoría" subtitle="Base para el inventario mensual y anual" flush>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Categoría</th>
                      <th className="num">Referencias</th>
                      <th className="num">Unidades</th>
                      <th className="num">Coste</th>
                      <th className="num">Venta</th>
                      <th className="num">Margen potencial</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.data.categories.map((item) => (
                      <tr key={item.category}>
                        <td className="strong">{item.category}</td>
                        <td className="num">{item.products}</td>
                        <td className="num">{fmtNumber(item.units, 0)}</td>
                        <td className="num">{fmtMoney(item.purchase_value)}</td>
                        <td className="num">{fmtMoney(item.sale_value)}</td>
                        <td className="num text-success">
                          {fmtMoney(Number(item.sale_value) - Number(item.purchase_value))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td>Total</td>
                      <td />
                      <td className="num">{fmtNumber(totalUnits, 0)}</td>
                      <td className="num">{fmtMoney(totalPurchase)}</td>
                      <td className="num">{fmtMoney(totalSale)}</td>
                      <td className="num text-success">{fmtMoney(totalSale - totalPurchase)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </Card>

            <div className="side-panel">
              <Card title="Exportaciones CSV" subtitle="Datos completos, sin muestras">
                <div className="stack" style={{ gap: 12 }}>
                  <div>
                    <button
                      type="button"
                      className="btn btn-block"
                      onClick={() => exportCsv("inventory")}
                      disabled={!can("reports.export") || busy === "inventory"}
                    >
                      {busy === "inventory" ? <span className="spinner" /> : <IconDownload />}
                      Inventario detallado
                    </button>
                    <p className="hint" style={{ marginTop: 5 }}>
                      SKU, ubicación, palé, físico, reservado, disponible, precios y valor.
                    </p>
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <Field label="Desde">
                      <input
                        className="input"
                        type="date"
                        value={dateFrom}
                        onChange={(event) => setDateFrom(event.target.value)}
                      />
                    </Field>
                    <Field label="Hasta">
                      <input
                        className="input"
                        type="date"
                        value={dateTo}
                        onChange={(event) => setDateTo(event.target.value)}
                      />
                    </Field>
                  </div>
                  <div>
                    <button
                      type="button"
                      className="btn btn-block"
                      onClick={() => exportCsv("movements")}
                      disabled={!can("reports.export") || busy === "movements"}
                    >
                      {busy === "movements" ? <span className="spinner" /> : <IconDownload />}
                      Movimientos
                    </button>
                    <p className="hint" style={{ marginTop: 5 }}>
                      Libro completo con tipo, estado, origen, destino, trabajador y confirmación física.
                    </p>
                  </div>
                  {!can("reports.export") ? (
                    <Badge tone="warning">Su perfil solo puede consultar, no exportar</Badge>
                  ) : null}
                </div>
              </Card>

              <div className="alert warning">
                <strong>PDF y Excel nativo · Fase 9</strong>
                <span>
                  Los informes CSV son reales y completos. La generación en PDF/Excel con plantillas y los
                  informes programados se implementarán en la fase de documentación avanzada; no se muestran
                  como disponibles.
                </span>
              </div>
            </div>
          </div>

          <Card title="Informes previstos" subtitle="Hoja de ruta de documentación">
            <div className="grid grid-3">
              {[
                ["Inventario diario / mensual / anual", "Programado"],
                ["Existencias por ubicación y valoración", "Disponible (CSV)"],
                ["Entradas y salidas por periodo", "Disponible (CSV)"],
                ["Facturación y conciliaciones", "Parcial (pantalla)"],
                ["Repartos y trabajadores", "Fase 7-8"],
                ["Incidencias y auditoría", "Auditoría disponible"],
              ].map(([title, status]) => (
                <div key={title} className="alert" style={{ borderLeftColor: "var(--accent)" }}>
                  <strong>{title}</strong>
                  <span>{status}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      ) : null}
    </>
  );
}
