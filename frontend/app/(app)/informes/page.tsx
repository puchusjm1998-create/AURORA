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

  async function exportReport(kind: "inventory" | "movements", format: "csv" | "pdf" | "xlsx") {
    const key = `${kind}-${format}`;
    setBusy(key);
    try {
      const params = new URLSearchParams();
      if (kind === "movements") {
        if (dateFrom) params.set("date_from", new Date(`${dateFrom}T00:00:00`).toISOString());
        if (dateTo) params.set("date_to", new Date(`${dateTo}T23:59:59`).toISOString());
      }
      const suffix = params.toString() ? `?${params.toString()}` : "";
      await downloadFile(`/api/v1/reports/${kind}.${format}${suffix}`, `aurora-${kind}.${format}`);
      const detail =
        format === "csv"
          ? "CSV completo en UTF-8."
          : format === "xlsx"
            ? "Excel nativo con resumen, filtros y totales."
            : "PDF paginado listo para imprimir o archivar.";
      toast.success("Informe descargado", detail);
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
              <Card title="Exportaciones nativas" subtitle="PDF, Excel y CSV con los datos completos">
                <div className="stack" style={{ gap: 12 }}>
                  <div>
                    <strong>Inventario detallado</strong>
                    <p className="hint" style={{ marginTop: 3 }}>
                      SKU, ubicación, palé, físico, reservado, disponible, precios y valor.
                    </p>
                    <div className="grid grid-3" style={{ gap: 6, marginTop: 8 }}>
                      {(["pdf", "xlsx", "csv"] as const).map((format) => (
                        <button
                          key={format}
                          type="button"
                          className={format === "xlsx" ? "btn btn-block" : "btn btn-ghost btn-block"}
                          onClick={() => exportReport("inventory", format)}
                          disabled={!can("reports.export") || busy === `inventory-${format}`}
                        >
                          {busy === `inventory-${format}` ? <span className="spinner" /> : <IconDownload />}
                          {format === "xlsx" ? "Excel" : format.toUpperCase()}
                        </button>
                      ))}
                    </div>
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
                    <strong>Libro de movimientos</strong>
                    <p className="hint" style={{ marginTop: 3 }}>
                      Tipo, estado, origen, destino, lote, documento y confirmación física.
                    </p>
                    <div className="grid grid-3" style={{ gap: 6, marginTop: 8 }}>
                      {(["pdf", "xlsx", "csv"] as const).map((format) => (
                        <button
                          key={format}
                          type="button"
                          className={format === "xlsx" ? "btn btn-block" : "btn btn-ghost btn-block"}
                          onClick={() => exportReport("movements", format)}
                          disabled={!can("reports.export") || busy === `movements-${format}`}
                        >
                          {busy === `movements-${format}` ? <span className="spinner" /> : <IconDownload />}
                          {format === "xlsx" ? "Excel" : format.toUpperCase()}
                        </button>
                      ))}
                    </div>
                  </div>
                  {!can("reports.export") ? (
                    <Badge tone="warning">Su perfil solo puede consultar, no exportar</Badge>
                  ) : null}
                </div>
              </Card>

              <div className="alert">
                <strong>Documentos reales, sin plantillas simuladas</strong>
                <span>
                  El PDF se genera paginado con cabecera repetida y totales; el Excel incluye hoja de resumen,
                  cabecera fija, autofiltro, formatos numéricos y fila de totales. Los informes programados por
                  correo siguen pendientes y no se anuncian como disponibles.
                </span>
              </div>
            </div>
          </div>

          <Card title="Cobertura de informes" subtitle="Qué se puede descargar hoy y qué queda pendiente">
            <div className="grid grid-3">
              {[
                ["Inventario y valoración", "PDF, Excel y CSV"],
                ["Entradas y salidas por periodo", "PDF, Excel y CSV"],
                ["Facturación y conciliaciones", "Pantalla (exportación pendiente)"],
                ["Repartos y trabajadores", "Pantalla (exportación pendiente)"],
                ["Incidencias y auditoría", "Pantalla y auditoría"],
                ["Envío programado por correo", "Pendiente"],
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
