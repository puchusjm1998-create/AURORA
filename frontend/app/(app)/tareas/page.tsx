"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import {
  fmtDateTime,
  fmtRelative,
  taskPriorityMeta,
  taskStatusMeta,
} from "@/lib/format";
import type { Employee, Page, Task, TaskStatus } from "@/lib/types";
import {
  Badge,
  Card,
  ConfirmDialog,
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
import {
  IconCheck,
  IconPlus,
  IconRefresh,
  IconTask,
  IconUsers,
} from "@/components/icons";

const LIMIT = 25;

function isOverdue(task: Task): boolean {
  if (!task.due_at || ["done", "cancelled"].includes(task.status)) return false;
  return new Date(task.due_at).getTime() < Date.now();
}

export default function TasksPage() {
  const { user, can } = useAuth();
  const toast = useToast();
  const isWorker = (user?.role_level ?? 5) >= 4;
  const [status, setStatus] = useState<string>("open");
  const [mine, setMine] = useState(isWorker && Boolean(user?.employee));
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("");
  const [offset, setOffset] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Task | null>(null);
  const [form, setForm] = useState({
    title: "",
    description: "",
    priority: "3",
    assigned_to: "",
    due_at: "",
  });
  const debounced = useDebounced(search, 280);

  const statusParam =
    status === "open"
      ? "pending,in_progress,blocked"
      : status === "all"
        ? null
        : status;

  const query = useMemo(
    () =>
      withQuery("/api/v1/tasks", {
        status: statusParam,
        mine: mine ? true : null,
        search: debounced || null,
        priority: priority || null,
        limit: LIMIT,
        offset,
      }),
    [statusParam, mine, debounced, priority, offset],
  );
  const tasks = useApi<Page<Task>>(query);
  const openCount = useApi<Page<Task>>("/api/v1/tasks?status=pending,in_progress,blocked&limit=1");
  const progressCount = useApi<Page<Task>>("/api/v1/tasks?status=in_progress&limit=1");
  const doneCount = useApi<Page<Task>>("/api/v1/tasks?status=done&limit=1");
  const employees = useApi<Page<Employee>>(
    can("tasks.write") && can("workers.read") ? "/api/v1/employees?status=active&limit=200" : null,
  );

  function reloadAll() {
    tasks.reload();
    openCount.reload();
    progressCount.reload();
    doneCount.reload();
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await api("/api/v1/tasks", {
        method: "POST",
        body: {
          title: form.title,
          description: form.description,
          priority: Number(form.priority),
          assigned_to: form.assigned_to || null,
          due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
        },
      });
      toast.success("Tarea creada", form.title);
      setOpen(false);
      setForm({ title: "", description: "", priority: "3", assigned_to: "", due_at: "" });
      reloadAll();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function run(task: Task, action: "start" | "complete" | "reopen") {
    setBusyId(task.id);
    try {
      await api(`/api/v1/tasks/${task.id}/${action}`, { method: "POST" });
      const message =
        action === "start" ? "Tarea iniciada" : action === "complete" ? "Tarea completada" : "Tarea reabierta";
      toast.success(message, task.code);
      reloadAll();
    } catch (err) {
      toast.error("No se pudo actualizar la tarea", errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function cancel() {
    if (!cancelTarget) return;
    setBusyId(cancelTarget.id);
    try {
      await api(`/api/v1/tasks/${cancelTarget.id}/cancel`, { method: "POST" });
      toast.success("Tarea cancelada", cancelTarget.code);
      setCancelTarget(null);
      reloadAll();
    } catch (err) {
      toast.error("No se pudo cancelar", errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  const canExecute = (task: Task) => {
    if (!can("tasks.complete")) return false;
    if (!isWorker) return true;
    return Boolean(user?.employee && task.assigned_to === user.employee.id);
  };

  return (
    <>
      <PageHeader
        eyebrow="Preparación"
        title="Tareas del almacén"
        subtitle="Planificación, asignación y cierre con confirmación humana. Cada cambio queda auditado."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={reloadAll} disabled={tasks.loading}>
              <IconRefresh /> Actualizar
            </button>
            {can("tasks.write") ? (
              <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
                <IconPlus /> Nueva tarea
              </button>
            ) : null}
          </>
        }
      />

      <div className="grid grid-3" style={{ marginBottom: 18 }}>
        <Stat
          label="Tareas abiertas"
          value={openCount.data?.total ?? "—"}
          meta={<span>pendientes, en curso o bloqueadas</span>}
          accent
        />
        <Stat
          label="En curso"
          value={progressCount.data?.total ?? "—"}
          meta={<span>trabajo iniciado por el equipo</span>}
        />
        <Stat
          label="Completadas"
          value={doneCount.data?.total ?? "—"}
          meta={<span>histórico, nunca se borra</span>}
        />
      </div>

      <section className="card">
        <div className="toolbar">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder="Buscar por código o título…"
          />
          <select
            className="select"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            aria-label="Estado de la tarea"
          >
            <option value="open">Abiertas</option>
            <option value="all">Todas</option>
            <option value="pending">Pendientes</option>
            <option value="in_progress">En curso</option>
            <option value="blocked">Bloqueadas</option>
            <option value="done">Completadas</option>
            <option value="cancelled">Canceladas</option>
          </select>
          <select
            className="select"
            value={priority}
            onChange={(event) => {
              setPriority(event.target.value);
              setOffset(0);
            }}
            aria-label="Prioridad"
          >
            <option value="">Cualquier prioridad</option>
            <option value="1">Crítica</option>
            <option value="2">Alta</option>
            <option value="3">Media</option>
            <option value="4">Baja</option>
            <option value="5">Mínima</option>
          </select>
          {user?.employee ? (
            <label className="check">
              <input
                type="checkbox"
                checked={mine}
                onChange={(event) => {
                  setMine(event.target.checked);
                  setOffset(0);
                }}
              />
              Solo mis tareas
            </label>
          ) : null}
          <span className="spacer" />
          <span className="count-chip">{tasks.data ? `${tasks.data.total} tareas` : "—"}</span>
        </div>

        {mine ? (
          <div className="alert" style={{ margin: "0 16px 12px" }}>
            <span>
              Mostrando únicamente las tareas asignadas a <b>{user?.employee?.first_name} {user?.employee?.last_name}</b>.
              Desmarque el filtro si necesita ver todo el equipo.
            </span>
          </div>
        ) : null}

        {tasks.error ? (
          <div style={{ padding: 16 }}>
            <ErrorBlock message={tasks.error} onRetry={tasks.reload} />
          </div>
        ) : null}
        {tasks.loading && !tasks.data ? <LoadingBlock label="Cargando tareas…" /> : null}
        {tasks.data && tasks.data.items.length === 0 ? (
          <EmptyState
            icon={<IconTask />}
            title={mine ? "No tiene tareas asignadas" : "Sin tareas"}
            description={
              can("tasks.write")
                ? "Cree una tarea para organizar la preparación de pedidos, el recuento o cualquier trabajo de almacén."
                : "Cuando un responsable le asigne trabajo aparecerá aquí. Puede actualizar para refrescar."
            }
            action={
              can("tasks.write") ? (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setOpen(true)}>
                  Nueva tarea
                </button>
              ) : undefined
            }
          />
        ) : null}

        {tasks.data && tasks.data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Código</th>
                    <th>Tarea</th>
                    <th>Prioridad</th>
                    <th>Asignada a</th>
                    <th>Vencimiento</th>
                    <th>Estado</th>
                    <th className="actions">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.data.items.map((task) => {
                    const statusMeta = taskStatusMeta[task.status] ?? { tone: "neutral", label: task.status };
                    const priorityMeta = taskPriorityMeta[task.priority] ?? taskPriorityMeta[3];
                    const overdue = isOverdue(task);
                    const executable = canExecute(task);
                    return (
                      <tr key={task.id}>
                        <td className="mono">{task.code}</td>
                        <td>
                          <div className="strong small">{task.title}</div>
                          {task.description ? (
                            <div className="tiny text-muted" style={{ maxWidth: 360 }}>
                              {task.description}
                            </div>
                          ) : null}
                        </td>
                        <td>
                          <Badge tone={priorityMeta.tone as "danger"}>
                            {task.priority} · {priorityMeta.label}
                          </Badge>
                        </td>
                        <td className="small">
                          {task.assignee_name ? (
                            <>
                              {task.assignee_name}
                              <div className="tiny mono text-muted">{task.assignee_code}</div>
                            </>
                          ) : (
                            <span className="text-muted">Sin asignar</span>
                          )}
                        </td>
                        <td className="small nowrap">
                          {task.due_at ? (
                            <span className={overdue ? "text-danger" : ""}>
                              {fmtDateTime(task.due_at)}
                              {overdue ? <div className="tiny">vencida</div> : null}
                            </span>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td>
                          <Badge tone={statusMeta.tone as "success"}>{statusMeta.label}</Badge>
                          {task.completed_at ? (
                            <div className="tiny text-muted">{fmtRelative(task.completed_at)}</div>
                          ) : null}
                        </td>
                        <td className="actions">
                          {executable && ["pending", "blocked"].includes(task.status) ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => run(task, "start")}
                              disabled={busyId === task.id}
                            >
                              Iniciar
                            </button>
                          ) : null}
                          {executable && ["pending", "in_progress"].includes(task.status) ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-success"
                              onClick={() => run(task, "complete")}
                              disabled={busyId === task.id}
                            >
                              <IconCheck /> Completar
                            </button>
                          ) : null}
                          {can("tasks.write") && ["pending", "in_progress", "blocked"].includes(task.status) ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => setCancelTarget(task)}
                              disabled={busyId === task.id}
                            >
                              Cancelar
                            </button>
                          ) : null}
                          {can("tasks.write") && ["done", "cancelled"].includes(task.status) ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => run(task, "reopen")}
                              disabled={busyId === task.id}
                            >
                              Reabrir
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination total={tasks.data.total} limit={tasks.data.limit} offset={tasks.data.offset} onChange={setOffset} />
          </>
        ) : null}
      </section>

      <div className="alert" style={{ marginTop: 14 }}>
        <strong>Trabajo real, no simulado</strong>
        <span>
          Las tareas no mueven stock por sí mismas: la mercancía se mueve con movimientos confirmados en{" "}
          <Link href="/operaciones">Operaciones</Link>. La tarea documenta el trabajo y su responsable.
        </span>
      </div>

      <Modal
        open={open}
        title="Nueva tarea"
        subtitle="Se asigna a un trabajador concreto y queda en el histórico"
        onClose={() => setOpen(false)}
        wide
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)} disabled={creating}>
              Cancelar
            </button>
            <button type="submit" form="task-form" className="btn btn-primary" disabled={creating}>
              {creating ? <span className="spinner" /> : <IconPlus />} Crear tarea
            </button>
          </>
        }
      >
        <form id="task-form" className="stack" onSubmit={create}>
          <Field label="Título" required>
            <input
              className="input"
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="Preparar pedido PED-2026-0001"
              required
              maxLength={160}
            />
          </Field>
          <Field label="Instrucciones">
            <textarea
              className="textarea"
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              placeholder="Productos, cantidades, ubicaciones y comprobaciones necesarias."
            />
          </Field>
          <div className="form-grid">
            <Field label="Prioridad" required>
              <select
                className="select"
                value={form.priority}
                onChange={(event) => setForm({ ...form, priority: event.target.value })}
              >
                <option value="1">1 · Crítica</option>
                <option value="2">2 · Alta</option>
                <option value="3">3 · Media</option>
                <option value="4">4 · Baja</option>
                <option value="5">5 · Mínima</option>
              </select>
            </Field>
            <Field label="Vencimiento" hint="Hora de Madrid">
              <input
                className="input"
                type="datetime-local"
                value={form.due_at}
                onChange={(event) => setForm({ ...form, due_at: event.target.value })}
              />
            </Field>
            <Field label="Asignar a" className="full" hint="Solo trabajadores activos">
              <select
                className="select"
                value={form.assigned_to}
                onChange={(event) => setForm({ ...form, assigned_to: event.target.value })}
              >
                <option value="">Sin asignar (bolsa de trabajo)</option>
                {employees.data?.items.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.code} · {employee.last_name}, {employee.first_name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {!employees.data?.items.length ? (
            <p className="hint">
              <IconUsers width={13} height={13} /> No hay trabajadores activos. Cree fichas en Personal para
              poder asignar tareas.
            </p>
          ) : null}
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(cancelTarget)}
        title="Cancelar tarea"
        message={
          <>
            Se cancelará <b>{cancelTarget?.code}</b> ({cancelTarget?.title}). La tarea se conserva en el
            histórico con su motivo de cierre y puede reabrirse si fue un error.
          </>
        }
        confirmLabel="Cancelar tarea"
        danger
        busy={Boolean(busyId)}
        onConfirm={cancel}
        onClose={() => setCancelTarget(null)}
      />
    </>
  );
}
