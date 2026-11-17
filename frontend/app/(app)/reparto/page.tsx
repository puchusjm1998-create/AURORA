"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { deliveryStatusMeta, fmtDateTime, fmtQty } from "@/lib/format";
import type { Delivery, Pallet } from "@/lib/types";
import { PalletPicker } from "@/components/pickers";
import {
  Badge,
  ConfirmDialog,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  Stat,
  useToast,
} from "@/components/ui";
import { IconClose, IconPlus, IconRefresh, IconTruck } from "@/components/icons";

function DeliveryDetail() {
  const params = useSearchParams();
  const id = params.get("id");
  const { can } = useAuth();
  const toast = useToast();
  const canWrite = can("deliveries.write");
  const delivery = useApi<Delivery>(id ? `/api/v1/deliveries/${id}` : null, [id]);

  const [pallet, setPallet] = useState<Pallet | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [failOpen, setFailOpen] = useState(false);
  const [reason, setReason] = useState("");

  const data = delivery.data;
  const meta = data ? deliveryStatusMeta[data.status] ?? { tone: "neutral", label: data.status } : null;
  const editable = data ? ["draft", "preparing"].includes(data.status) : false;
  const removable = data ? ["draft", "preparing", "ready"].includes(data.status) : false;

  async function run(path: string, key: string, success: string) {
    if (!data) return;
    setBusy(key);
    setError(null);
    try {
      await api(`/api/v1/deliveries/${data.id}/${path}`, { method: "POST" });
      toast.success(success, data.reference);
      delivery.reload();
    } catch (err) {
      setError(errorMessage(err));
      toast.error("No se pudo completar", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function addPallet() {
    if (!data || !pallet) {
      setError("Seleccione un palé precintado.");
      return;
    }
    setBusy("pallet");
    setError(null);
    try {
      await api(`/api/v1/deliveries/${data.id}/pallets`, {
        method: "POST",
        body: { pallet_id: pallet.id },
      });
      toast.success("Palé añadido", pallet.code);
      setPallet(null);
      delivery.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function removePallet(palletId: string, code: string) {
    if (!data) return;
    setBusy(palletId);
    setError(null);
    try {
      await api(`/api/v1/deliveries/${data.id}/pallets/${palletId}`, { method: "DELETE" });
      toast.success("Palé retirado", code);
      delivery.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function fail(event: React.FormEvent) {
    event.preventDefault();
    if (!data) return;
    if (reason.trim().length < 5) {
      setError("Explique el motivo del fallo (mínimo 5 caracteres).");
      return;
    }
    setBusy("fail");
    setError(null);
    try {
      await api(`/api/v1/deliveries/${data.id}/fail`, {
        method: "POST",
        body: { reason: reason.trim() },
      });
      toast.success("Entrega marcada como fallida", data.reference);
      setFailOpen(false);
      setReason("");
      delivery.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function removeDelivery() {
    if (!data) return;
    setBusy("delete");
    try {
      await api(`/api/v1/deliveries/${data.id}`, { method: "DELETE" });
      toast.success("Borrador eliminado", data.reference);
      window.location.href = "/repartos/";
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
      setDeleteOpen(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Reparto"
        title={data ? data.reference : "Detalle de reparto"}
        subtitle={data ? data.destination_name : "Cargando…"}
        actions={
          <>
            <Link href="/repartos" className="btn btn-ghost">
              Volver
            </Link>
            <button type="button" className="btn btn-ghost" onClick={delivery.reload} disabled={delivery.loading}>
              <IconRefresh /> Actualizar
            </button>
          </>
        }
      />

      {delivery.error ? <ErrorBlock message={delivery.error} onRetry={delivery.reload} /> : null}
      {delivery.loading && !data ? <LoadingBlock label="Cargando reparto…" /> : null}

      {data ? (
        <>
          <div className="grid grid-4" style={{ marginBottom: 18 }}>
            <Stat label="Estado" value={<Badge tone={meta?.tone as "info"}>{meta?.label}</Badge>} meta={<span>{data.reference}</span>} accent />
            <Stat label="Palés" value={data.pallets.length} meta={<span>{fmtQty(data.total_units)} unidades</span>} />
            <Stat
              label="Salida prevista"
              value={data.planned_departure ? fmtDateTime(data.planned_departure) : "—"}
              meta={<span>{data.vehicle_plate ?? "sin vehículo"}</span>}
            />
            <Stat
              label="Conductor"
              value={data.driver_name ?? "—"}
              meta={<span>{data.departed_at ? `salió ${fmtDateTime(data.departed_at)}` : "sin salir"}</span>}
            />
          </div>

          {error ? <div className="form-error" style={{ marginBottom: 14 }}>{error}</div> : null}

          <section className="card" style={{ marginBottom: 18 }}>
            <div className="card-body">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <div className="eyebrow">Mercancía del reparto</div>
                  <div className="strong" style={{ fontSize: 16 }}>
                    {data.pallets.length} palés · {fmtQty(data.total_units)} unidades
                  </div>
                </div>
                {canWrite && editable ? (
                  <div className="row">
                    <div style={{ minWidth: 280 }}>
                      <PalletPicker value={pallet?.id ?? null} onChange={setPallet} status="sealed" />
                    </div>
                    <button type="button" className="btn btn-primary" onClick={addPallet} disabled={busy === "pallet"}>
                      {busy === "pallet" ? <span className="spinner" /> : <IconPlus />} Añadir palé
                    </button>
                  </div>
                ) : null}
              </div>

              {data.pallets.length === 0 ? (
                <div className="alert warning" style={{ marginTop: 12 }}>
                  <strong>Sin palés</strong>
                  <span>
                    Añada palés precintados para poder marcar el reparto como listo y cargar la
                    mercancía.
                  </span>
                </div>
              ) : (
                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Palé</th>
                        <th>Ubicación</th>
                        <th>Contenido</th>
                        <th className="num">Unidades</th>
                        <th className="actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {data.pallets.map((item) => (
                        <tr key={item.pallet_id}>
                          <td className="mono">
                            <Link href={`/pale?id=${item.pallet_id}`} className="text-accent">
                              {item.pallet_code}
                            </Link>
                          </td>
                          <td className="small mono">{item.location_code ?? "—"}</td>
                          <td className="small">
                            {item.items.map((line) => (
                              <div key={`${item.pallet_id}-${line.product_id}`}>
                                {line.product_sku} · {line.product_name} · {fmtQty(line.quantity)}
                              </div>
                            ))}
                          </td>
                          <td className="num">{fmtQty(item.total_units)}</td>
                          <td className="actions">
                            {canWrite && removable ? (
                              <button
                                type="button"
                                className="btn btn-sm btn-ghost"
                                onClick={() => removePallet(item.pallet_id, item.pallet_code)}
                                disabled={busy === item.pallet_id}
                              >
                                <IconClose /> Quitar
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {canWrite ? (
                <div className="row" style={{ marginTop: 16 }}>
                  {data.status === "draft" ? (
                    <button type="button" className="btn btn-primary" onClick={() => run("prepare", "prepare", "Preparación iniciada")} disabled={Boolean(busy)}>
                      Iniciar preparación
                    </button>
                  ) : null}
                  {data.status === "preparing" ? (
                    <button type="button" className="btn btn-primary" onClick={() => run("ready", "ready", "Reparto listo")} disabled={Boolean(busy)}>
                      Marcar listo
                    </button>
                  ) : null}
                  {data.status === "ready" ? (
                    <button type="button" className="btn btn-primary" onClick={() => run("load", "load", "Mercancía cargada y expedida")} disabled={Boolean(busy)}>
                      {busy === "load" ? <span className="spinner" /> : <IconTruck />} Cargar y expedir
                    </button>
                  ) : null}
                  {data.status === "loaded" ? (
                    <button type="button" className="btn btn-primary" onClick={() => run("dispatch", "dispatch", "Transporte iniciado")} disabled={Boolean(busy)}>
                      Iniciar transporte
                    </button>
                  ) : null}
                  {data.status === "in_transit" ? (
                    <>
                      <button type="button" className="btn btn-primary" onClick={() => run("deliver", "deliver", "Entrega confirmada")} disabled={Boolean(busy)}>
                        Marcar entregado
                      </button>
                      <button type="button" className="btn btn-ghost" onClick={() => setFailOpen(true)} disabled={Boolean(busy)}>
                        Entrega fallida
                      </button>
                    </>
                  ) : null}
                  {["draft", "preparing", "ready"].includes(data.status) ? (
                    <button type="button" className="btn btn-ghost" onClick={() => setCancelOpen(true)} disabled={Boolean(busy)}>
                      Cancelar reparto
                    </button>
                  ) : null}
                  {data.status === "draft" ? (
                    <button type="button" className="btn btn-ghost" onClick={() => setDeleteOpen(true)} disabled={Boolean(busy)}>
                      Eliminar borrador
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </section>

          <section className="card">
            <div className="card-body">
              <div className="eyebrow">Información del reparto</div>
              <div className="grid grid-2" style={{ marginTop: 10 }}>
                <div>
                  <div className="tiny text-muted">Dirección</div>
                  <div className="small">{data.destination_address || "—"}</div>
                  <div className="tiny text-muted" style={{ marginTop: 8 }}>
                    Vehículo
                  </div>
                  <div className="small">{data.vehicle_plate ? `${data.vehicle_plate}` : "Sin asignar"}</div>
                </div>
                <div>
                  <div className="tiny text-muted">Cronología</div>
                  <div className="small">Creado: {fmtDateTime(data.created_at)}</div>
                  <div className="small">
                    Salida: {data.departed_at ? fmtDateTime(data.departed_at) : "pendiente"}
                  </div>
                  <div className="small">
                    Entrega: {data.delivered_at ? fmtDateTime(data.delivered_at) : "pendiente"}
                  </div>
                </div>
              </div>
              {data.notes ? <p className="small text-muted" style={{ marginTop: 10 }}>{data.notes}</p> : null}
            </div>
          </section>

          <div className="alert" style={{ marginTop: 14 }}>
            <strong>El stock sale al cargar</strong>
            <span>
              Cargar el reparto genera una salida confirmada por cada producto de cada palé y deja el
              palé en tránsito. Después, el reparto solo avanza por hitos de transporte y ya no se edita.
            </span>
          </div>
        </>
      ) : null}

      <ConfirmDialog
        open={cancelOpen}
        title="Cancelar reparto"
        message="Se liberarán los palés asignados y el reparto quedará cancelado. No se mueve stock."
        confirmLabel="Cancelar reparto"
        danger
        busy={busy === "cancel"}
        onConfirm={() => {
          setCancelOpen(false);
          run("cancel", "cancel", "Reparto cancelado");
        }}
        onClose={() => setCancelOpen(false)}
      />

      <ConfirmDialog
        open={deleteOpen}
        title="Eliminar borrador"
        message="El borrador se eliminará definitivamente. Esta acción queda auditada."
        confirmLabel="Eliminar"
        danger
        busy={busy === "delete"}
        onConfirm={removeDelivery}
        onClose={() => setDeleteOpen(false)}
      />

      <Modal
        open={failOpen}
        title="Entrega fallida"
        subtitle="La mercancía ya salió del almacén; documente qué ha pasado"
        onClose={() => setFailOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setFailOpen(false)} disabled={busy === "fail"}>
              Cancelar
            </button>
            <button type="submit" form="fail-form" className="btn btn-danger" disabled={busy === "fail"}>
              {busy === "fail" ? <span className="spinner" /> : null} Marcar fallida
            </button>
          </>
        }
      >
        <form id="fail-form" className="stack" onSubmit={fail}>
          <Field label="Motivo" required hint="Quedará en las notas del reparto y en la auditoría.">
            <textarea
              className="input"
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Cliente cerrado, dirección incorrecta, mercancía rechazada…"
              required
            />
          </Field>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>
    </>
  );
}

export default function DeliveryDetailPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <DeliveryDetail />
    </Suspense>
  );
}
