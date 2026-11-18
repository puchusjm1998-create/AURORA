"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import { deliveryStatusMeta, fmtDateTime, fmtQty } from "@/lib/format";
import type { Delivery, Employee, Page, Vehicle } from "@/lib/types";
import {
  Badge,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  Pagination,
  SearchInput,
  Stat,
  useToast,
} from "@/components/ui";
import { IconPlus, IconRefresh, IconTruck } from "@/components/icons";

const LIMIT = 25;
const ACTIVE = "draft,preparing,ready,loaded,in_transit";

export default function DeliveriesPage() {
  const { can } = useAuth();
  const toast = useToast();
  const canWrite = can("deliveries.write");
  const [status, setStatus] = useState(ACTIVE);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const debounced = useDebounced(search, 280);

  const deliveries = useApi<Page<Delivery>>(
    useMemo(
      () =>
        withQuery("/api/v1/deliveries", {
          status: status || null,
          search: debounced || null,
          limit: LIMIT,
          offset,
        }),
      [status, debounced, offset],
    ),
  );
  const pending = useApi<Page<Delivery>>(
    "/api/v1/deliveries?status=draft,preparing,ready&limit=1",
  );
  const transit = useApi<Page<Delivery>>(
    "/api/v1/deliveries?status=loaded,in_transit&limit=1",
  );
  const delivered = useApi<Page<Delivery>>("/api/v1/deliveries?status=delivered&limit=1");
  const failed = useApi<Page<Delivery>>("/api/v1/deliveries?status=failed&limit=1");

  const vehicles = useApi<Page<Vehicle>>("/api/v1/vehicles?limit=200");
  const employees = useApi<Page<Employee>>(
    can("workers.read") ? "/api/v1/employees?status=active&limit=200" : null,
  );

  const [openDelivery, setOpenDelivery] = useState(false);
  const [openVehicle, setOpenVehicle] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    destination_name: "",
    destination_address: "",
    vehicle_id: "",
    driver_employee_id: "",
    planned_departure: "",
    notes: "",
  });
  const [vehicleForm, setVehicleForm] = useState({ plate: "", model: "", capacity_kg: "" });

  function newDelivery() {
    setForm({
      destination_name: "",
      destination_address: "",
      vehicle_id: "",
      driver_employee_id: "",
      planned_departure: "",
      notes: "",
    });
    setError(null);
    setOpenDelivery(true);
  }

  async function createDelivery(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api<Delivery>("/api/v1/deliveries", {
        method: "POST",
        body: {
          destination_name: form.destination_name.trim(),
          destination_address: form.destination_address.trim(),
          vehicle_id: form.vehicle_id || null,
          driver_employee_id: form.driver_employee_id || null,
          planned_departure: form.planned_departure
            ? new Date(form.planned_departure).toISOString()
            : null,
          notes: form.notes.trim(),
        },
      });
      toast.success("Reparto creado", created.reference);
      setOpenDelivery(false);
      deliveries.reload();
      pending.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function createVehicle(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/vehicles", {
        method: "POST",
        body: {
          plate: vehicleForm.plate.trim(),
          model: vehicleForm.model.trim(),
          capacity_kg: vehicleForm.capacity_kg ? vehicleForm.capacity_kg : null,
        },
      });
      toast.success("Vehículo creado", vehicleForm.plate.toUpperCase());
      setOpenVehicle(false);
      vehicles.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleVehicle(vehicle: Vehicle) {
    try {
      await api(`/api/v1/vehicles/${vehicle.id}`, {
        method: "PATCH",
        body: { is_active: !vehicle.is_active },
      });
      vehicles.reload();
    } catch (err) {
      toast.error("No se pudo actualizar", errorMessage(err));
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Expedición"
        title="Repartos y vehículos"
        subtitle="Agrupe palés precintados en un reparto. Al cargarlo se genera una salida de stock auditada por cada producto; después solo quedan los hitos del transporte."
        actions={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={deliveries.reload}
              disabled={deliveries.loading}
            >
              <IconRefresh /> Actualizar
            </button>
            {canWrite ? (
              <button type="button" className="btn btn-primary" onClick={newDelivery}>
                <IconPlus /> Nuevo reparto
              </button>
            ) : null}
          </>
        }
      />

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Stat
          label="Por preparar"
          value={pending.data?.total ?? "—"}
          meta={<span>borradores, preparación y listos</span>}
          accent
        />
        <Stat
          label="En tránsito"
          value={transit.data?.total ?? "—"}
          meta={<span>cargados o ya en ruta</span>}
        />
        <Stat label="Entregados" value={delivered.data?.total ?? "—"} meta={<span>con palés enviados</span>} />
        <Stat label="Fallidos" value={failed.data?.total ?? "—"} meta={<span>requieren seguimiento</span>} />
      </div>

      <section className="card" style={{ marginBottom: 18 }}>
        <div className="toolbar">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder="Buscar por referencia o destino…"
          />
          <select
            className="select"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            aria-label="Estado"
          >
            <option value={ACTIVE}>Activos</option>
            <option value="delivered">Entregados</option>
            <option value="failed">Fallidos</option>
            <option value="cancelled">Cancelados</option>
            <option value="">Todos</option>
          </select>
          <span className="spacer" />
          <span className="count-chip">
            {deliveries.data ? `${deliveries.data.total} repartos` : "—"}
          </span>
        </div>

        {deliveries.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={deliveries.error} onRetry={deliveries.reload} />
          </div>
        ) : null}
        {deliveries.loading && !deliveries.data ? <LoadingBlock label="Cargando repartos…" /> : null}
        {deliveries.data && deliveries.data.items.length === 0 ? (
          <EmptyState
            icon={<IconTruck />}
            title="Sin repartos"
            description={
              canWrite
                ? "Cree un reparto, añada palés precintados y cárguelo para expedir la mercancía."
                : "No hay repartos que coincidan con el filtro."
            }
            action={
              canWrite ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={newDelivery}>
                  Nuevo reparto
                </button>
              ) : undefined
            }
          />
        ) : null}
        {deliveries.data && deliveries.data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Reparto</th>
                    <th>Destino</th>
                    <th>Vehículo</th>
                    <th>Conductor</th>
                    <th>Salida prevista</th>
                    <th className="num">Palés</th>
                    <th className="num">Unidades</th>
                    <th>Estado</th>
                    <th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {deliveries.data.items.map((delivery) => {
                    const meta = deliveryStatusMeta[delivery.status] ?? {
                      tone: "neutral",
                      label: delivery.status,
                    };
                    return (
                      <tr key={delivery.id}>
                        <td className="mono">{delivery.reference}</td>
                        <td>
                          <div className="strong small">{delivery.destination_name}</div>
                          <div className="tiny text-muted">{delivery.destination_address}</div>
                        </td>
                        <td className="small">{delivery.vehicle_plate ?? "—"}</td>
                        <td className="small">{delivery.driver_name ?? "—"}</td>
                        <td className="small nowrap">
                          {delivery.planned_departure ? fmtDateTime(delivery.planned_departure) : "—"}
                        </td>
                        <td className="num">{delivery.pallets.length}</td>
                        <td className="num">{fmtQty(delivery.total_units)}</td>
                        <td>
                          <Badge tone={meta.tone as "info"}>{meta.label}</Badge>
                        </td>
                        <td className="actions">
                          <Link href={`/reparto?id=${delivery.id}`} className="btn btn-sm btn-ghost">
                            Abrir
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination
              total={deliveries.data.total}
              limit={deliveries.data.limit}
              offset={deliveries.data.offset}
              onChange={setOffset}
            />
          </>
        ) : null}
      </section>

      <section className="card">
        <div className="toolbar">
          <strong className="small">Vehículos</strong>
          <span className="spacer" />
          {canWrite ? (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => {
                setVehicleForm({ plate: "", model: "", capacity_kg: "" });
                setError(null);
                setOpenVehicle(true);
              }}
            >
              <IconPlus /> Añadir vehículo
            </button>
          ) : null}
        </div>
        {vehicles.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={vehicles.error} onRetry={vehicles.reload} />
          </div>
        ) : null}
        {vehicles.loading && !vehicles.data ? <LoadingBlock label="Cargando vehículos…" /> : null}
        {vehicles.data && vehicles.data.items.length === 0 ? (
          <EmptyState
            icon={<IconTruck />}
            title="Sin vehículos"
            description="Registre la flota para asignar vehículo y capacidad a cada reparto."
          />
        ) : null}
        {vehicles.data && vehicles.data.items.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Matrícula</th>
                  <th>Modelo</th>
                  <th className="num">Capacidad</th>
                  <th>Estado</th>
                  <th className="actions" />
                </tr>
              </thead>
              <tbody>
                {vehicles.data.items.map((vehicle) => (
                  <tr key={vehicle.id}>
                    <td className="mono strong">{vehicle.plate}</td>
                    <td className="small">{vehicle.model || "—"}</td>
                    <td className="num">
                      {vehicle.capacity_kg ? `${fmtQty(vehicle.capacity_kg, "kg")}` : "—"}
                    </td>
                    <td>
                      <Badge tone={vehicle.is_active ? "success" : "neutral"}>
                        {vehicle.is_active ? "Activo" : "Inactivo"}
                      </Badge>
                    </td>
                    <td className="actions">
                      {canWrite ? (
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => toggleVehicle(vehicle)}
                        >
                          {vehicle.is_active ? "Desactivar" : "Activar"}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <Modal
        open={openDelivery}
        title="Nuevo reparto"
        subtitle="El stock se descuenta al cargar, no al crear"
        onClose={() => setOpenDelivery(false)}
        wide
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpenDelivery(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="delivery-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Crear reparto
            </button>
          </>
        }
      >
        <form id="delivery-form" className="stack" onSubmit={createDelivery}>
          <div className="form-grid">
            <Field label="Destino" required>
              <input
                className="input"
                value={form.destination_name}
                onChange={(event) => setForm({ ...form, destination_name: event.target.value })}
                placeholder="Cliente o punto de entrega"
                maxLength={150}
                required
              />
            </Field>
            <Field label="Dirección">
              <input
                className="input"
                value={form.destination_address}
                onChange={(event) => setForm({ ...form, destination_address: event.target.value })}
                maxLength={255}
              />
            </Field>
            <Field label="Vehículo">
              <select
                className="select"
                value={form.vehicle_id}
                onChange={(event) => setForm({ ...form, vehicle_id: event.target.value })}
              >
                <option value="">Sin asignar</option>
                {vehicles.data?.items
                  .filter((vehicle) => vehicle.is_active)
                  .map((vehicle) => (
                    <option key={vehicle.id} value={vehicle.id}>
                      {vehicle.plate} · {vehicle.model}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Conductor">
              <select
                className="select"
                value={form.driver_employee_id}
                onChange={(event) => setForm({ ...form, driver_employee_id: event.target.value })}
              >
                <option value="">Sin asignar</option>
                {employees.data?.items.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.first_name} {employee.last_name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Salida prevista" className="full">
              <input
                className="input"
                type="datetime-local"
                value={form.planned_departure}
                onChange={(event) => setForm({ ...form, planned_departure: event.target.value })}
              />
            </Field>
            <Field label="Notas" className="full">
              <textarea
                className="input"
                rows={2}
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
                maxLength={2000}
              />
            </Field>
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <Modal
        open={openVehicle}
        title="Nuevo vehículo"
        onClose={() => setOpenVehicle(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpenVehicle(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="vehicle-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Guardar
            </button>
          </>
        }
      >
        <form id="vehicle-form" className="stack" onSubmit={createVehicle}>
          <div className="form-grid">
            <Field label="Matrícula" required>
              <input
                className="input mono"
                value={vehicleForm.plate}
                onChange={(event) => setVehicleForm({ ...vehicleForm, plate: event.target.value })}
                placeholder="1234 ABC"
                maxLength={16}
                required
              />
            </Field>
            <Field label="Modelo">
              <input
                className="input"
                value={vehicleForm.model}
                onChange={(event) => setVehicleForm({ ...vehicleForm, model: event.target.value })}
                placeholder="Iveco Daily"
                maxLength={80}
              />
            </Field>
            <Field label="Capacidad (kg)" className="full">
              <input
                className="input"
                type="number"
                min="0"
                step="1"
                value={vehicleForm.capacity_kg}
                onChange={(event) => setVehicleForm({ ...vehicleForm, capacity_kg: event.target.value })}
              />
            </Field>
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>
    </>
  );
}
