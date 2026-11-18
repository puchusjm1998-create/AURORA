"use client";

import { useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, fmtNumber } from "@/lib/format";
import type { CalibrationState, TimeSample } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import {
  Badge,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  useToast,
} from "@/components/ui";
import { IconCheck, IconRefresh, IconRoute, IconTrash } from "@/components/icons";

const PARAMETERS: { key: string; label: string; unit: string; step: string; hint?: string }[] = [
  { key: "aisle_pitch_m", label: "Paso entre pasillos", unit: "m", step: "0.1" },
  { key: "rack_pitch_m", label: "Paso entre estanterías", unit: "m", step: "0.1" },
  { key: "position_pitch_m", label: "Paso entre posiciones", unit: "m", step: "0.1" },
  { key: "base_pick_seconds", label: "Tiempo base por parada", unit: "s", step: "0.5" },
  { key: "level_penalty_seconds", label: "Penalización por nivel", unit: "s", step: "0.5" },
  { key: "walking_speed_mps", label: "Velocidad de marcha", unit: "m/s", step: "0.01" },
  { key: "setup_seconds", label: "Preparación fija", unit: "s", step: "1" },
];

const DEFAULTS: Record<string, string> = {
  aisle_pitch_m: "3",
  rack_pitch_m: "6",
  position_pitch_m: "1",
  base_pick_seconds: "25",
  level_penalty_seconds: "6",
  walking_speed_mps: "1",
  setup_seconds: "0",
};

export function CalibrationPanel({
  refreshToken = 0,
  onChanged,
}: {
  refreshToken?: number;
  onChanged?: () => void;
}) {
  const { can } = useAuth();
  const toast = useToast();
  const canManage = can("locations.write");
  const calibration = useApi<CalibrationState>(
    `/api/v1/optimization/calibration?refresh=${refreshToken}`,
    [refreshToken],
  );
  const [form, setForm] = useState<Record<string, string>>(DEFAULTS);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [fitting, setFitting] = useState(false);
  const [toDelete, setToDelete] = useState<TimeSample | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!calibration.data) return;
    const values = { ...DEFAULTS };
    Object.keys(DEFAULTS).forEach((key) => {
      const value = calibration.data?.parameters[key];
      if (typeof value === "number") values[key] = String(value);
    });
    setForm(values);
    setNotes(calibration.data.notes ?? "");
  }, [calibration.data]);

  async function save() {
    setSaving(true);
    try {
      const body: Record<string, unknown> = { notes };
      PARAMETERS.forEach((parameter) => {
        body[parameter.key] = form[parameter.key];
      });
      if (calibration.data?.warehouse_id) body.warehouse_id = calibration.data.warehouse_id;
      await api<CalibrationState>("/api/v1/optimization/calibration", {
        method: "PUT",
        body,
      });
      toast.success("Calibración guardada", "Las rutas y el slotting usan ya estos valores.");
      calibration.reload();
      onChanged?.();
    } catch (err) {
      toast.error("No se pudo guardar", errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function fit() {
    setFitting(true);
    try {
      const query = calibration.data?.warehouse_id
        ? `?warehouse_id=${calibration.data.warehouse_id}`
        : "";
      await api<CalibrationState>(`/api/v1/optimization/calibration/fit${query}`, {
        method: "POST",
      });
      toast.success("Modelo ajustado", "Velocidad, tiempo de parada y preparación recalculados.");
      calibration.reload();
      onChanged?.();
    } catch (err) {
      toast.error("No se pudo ajustar", errorMessage(err));
    } finally {
      setFitting(false);
    }
  }

  async function removeSample() {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api(`/api/v1/optimization/time-studies/${toDelete.id}`, { method: "DELETE" });
      toast.success("Cronometraje eliminado");
      setToDelete(null);
      calibration.reload();
      onChanged?.();
    } catch (err) {
      toast.error("No se pudo eliminar", errorMessage(err));
    } finally {
      setDeleting(false);
    }
  }

  const data = calibration.data;

  return (
    <div className="stack" style={{ gap: 18 }}>
      <Card
        title="Calibración del almacén"
        subtitle="Parámetros del plano y tiempos medidos en campo; sustituyen a los valores por defecto"
        actions={
          <div className="row" style={{ gap: 6 }}>
            {data ? (
              <Badge tone={data.is_default ? "warning" : "success"}>
                {data.is_default ? "Sin calibrar" : data.method === "regression" ? "Regresión" : "Manual"}
              </Badge>
            ) : null}
            <button type="button" className="btn btn-sm btn-ghost" onClick={calibration.reload}>
              <IconRefresh /> Recargar
            </button>
          </div>
        }
      >
        {calibration.error ? <ErrorBlock message={calibration.error} onRetry={calibration.reload} /> : null}
        {calibration.loading && !data ? <LoadingBlock label="Cargando calibración…" /> : null}
        {data ? (
          <div className="stack" style={{ gap: 14 }}>
            <div className="row" style={{ gap: 8 }}>
              <span className="small text-muted">
                {data.warehouse_name ? `${data.warehouse_name} (${data.warehouse_code})` : "Sin almacén"}
              </span>
              <span className="count-chip">{data.total_samples} rutas cronometradas</span>
              {data.r_squared !== null ? (
                <Badge tone={data.r_squared >= 0.8 ? "success" : "warning"} dot={false}>
                  R² {data.r_squared.toFixed(3)}
                </Badge>
              ) : null}
              {data.mae_seconds !== null ? (
                <Badge tone="neutral" dot={false}>MAE {fmtNumber(data.mae_seconds, 1)} s</Badge>
              ) : null}
              {data.calibrated_at ? (
                <span className="tiny text-muted">
                  {data.calibrated_by ? `${data.calibrated_by} · ` : ""}
                  {fmtDateTime(data.calibrated_at)}
                </span>
              ) : null}
            </div>

            <div className="form-grid">
              {PARAMETERS.map((parameter) => (
                <Field
                  key={parameter.key}
                  label={`${parameter.label} (${parameter.unit})`}
                  hint={
                    parameter.key === "walking_speed_mps"
                      ? "Se recalcula al ajustar con tiempos reales"
                      : undefined
                  }
                >
                  <input
                    className="input"
                    type="number"
                    min="0"
                    step={parameter.step}
                    value={form[parameter.key] ?? ""}
                    onChange={(event) => setForm({ ...form, [parameter.key]: event.target.value })}
                    disabled={!canManage}
                  />
                </Field>
              ))}
              <Field label="Notas de calibración" className="full">
                <textarea
                  className="textarea"
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  disabled={!canManage}
                  placeholder="Plano medido con cinta métrica el 12/11; velocidad medida en 3 recorridos…"
                />
              </Field>
            </div>

            {canManage ? (
              <div className="row" style={{ gap: 8 }}>
                <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
                  {saving ? <span className="spinner" /> : <IconCheck />} Guardar calibración
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={fit}
                  disabled={fitting || data.total_samples < 3}
                  title={data.total_samples < 3 ? "Registre al menos 3 rutas cronometradas" : undefined}
                >
                  {fitting ? <span className="spinner" /> : <IconRoute />} Ajustar con tiempos medidos
                </button>
                {!data.is_default ? (
                  <span className="tiny text-muted">
                    El ajuste solo cambia velocidad, tiempo de parada y preparación; las distancias se
                    editan a mano.
                  </span>
                ) : null}
              </div>
            ) : (
              <p className="small text-muted">Solo lectura: su perfil no puede modificar la calibración.</p>
            )}
          </div>
        ) : null}
      </Card>

      <Card
        title="Cronometrajes registrados"
        subtitle="Cada muestra fija una ruta real y su tiempo; cuanto más variadas, mejor el ajuste"
        flush
      >
        {data && data.samples.length === 0 ? (
          <EmptyState
            icon={<IconRoute />}
            title="Sin tiempos medidos"
            description="Calcule una ruta en la sección de picking y cronométrela con el botón «Registrar tiempo»."
          />
        ) : null}
        {data && data.samples.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th className="num">Paradas</th>
                  <th className="num">Distancia modelo</th>
                  <th className="num">Tiempo medido</th>
                  <th>Notas</th>
                  <th>Registrado por</th>
                  {canManage ? <th /> : null}
                </tr>
              </thead>
              <tbody>
                {data.samples.map((sample) => (
                  <tr key={sample.id}>
                    <td className="small nowrap">{fmtDateTime(sample.measured_at)}</td>
                    <td className="num">{sample.stops}</td>
                    <td className="num">{fmtNumber(sample.distance_m, 1)} m</td>
                    <td className="num strong">{sample.measured_seconds} s</td>
                    <td className="small text-muted">{sample.notes || "—"}</td>
                    <td className="small">{sample.measurer_name ?? "—"}</td>
                    {canManage ? (
                      <td className="actions">
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => setToDelete(sample)}
                          aria-label="Eliminar cronometraje"
                        >
                          <IconTrash />
                        </button>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <ConfirmDialog
        open={toDelete !== null}
        title="Eliminar cronometraje"
        message={
          <>
            Se eliminará la muestra de <strong>{toDelete?.measured_seconds} s</strong> con{" "}
            {toDelete?.stops} parada(s). El ajuste actual no cambia hasta que vuelva a ajustarlo.
          </>
        }
        confirmLabel="Eliminar"
        danger
        busy={deleting}
        onConfirm={removeSample}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}
