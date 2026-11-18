"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, errorMessage, withQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced, useApi } from "@/lib/useApi";
import { employeeStatusMeta, fmtDate, fmtDateTime, initials, roleLevelLabel } from "@/lib/format";
import type { Employee, Page, Role, UserAccount } from "@/lib/types";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBlock,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  Pagination,
  SearchInput,
  Tabs,
  useToast,
} from "@/components/ui";
import {
  IconCheck,
  IconKey,
  IconPlus,
  IconPrint,
  IconRefresh,
  IconUsers,
} from "@/components/icons";

type Tab = "employees" | "users" | "roles";

const EMPTY_EMPLOYEE = {
  first_name: "",
  last_name: "",
  department: "",
  position: "",
  status: "active",
  hire_date: "",
  phone: "",
  weekly_hours: "40",
};

export default function PeoplePage() {
  const { can, user } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("employees");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const debounced = useDebounced(search, 280);

  const employees = useApi<Page<Employee>>(
    useMemo(
      () =>
        withQuery("/api/v1/employees", {
          search: debounced || null,
          status: status || null,
          limit: 50,
          offset,
        }),
      [debounced, status, offset],
    ),
  );
  const users = useApi<Page<UserAccount>>(tab === "users" && can("users.manage") ? "/api/v1/users?limit=200" : null);
  const roles = useApi<Role[]>(tab === "roles" ? "/api/v1/roles" : null);

  const [employeeOpen, setEmployeeOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [empForm, setEmpForm] = useState(EMPTY_EMPLOYEE);
  const [userOpen, setUserOpen] = useState(false);
  const [userForm, setUserForm] = useState({
    email: "",
    full_name: "",
    password: "",
    role_level: "4",
    employee_id: "",
    must_change_password: true,
  });
  const [resetUser, setResetUser] = useState<UserAccount | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function openCreateEmployee() {
    setEditing(null);
    setEmpForm(EMPTY_EMPLOYEE);
    setError(null);
    setEmployeeOpen(true);
  }

  function openEditEmployee(employee: Employee) {
    setEditing(employee);
    setEmpForm({
      first_name: employee.first_name,
      last_name: employee.last_name,
      department: employee.department,
      position: employee.position,
      status: employee.status,
      hire_date: employee.hire_date ?? "",
      phone: employee.phone ?? "",
      weekly_hours: String(employee.weekly_hours ?? "40"),
    });
    setError(null);
    setEmployeeOpen(true);
  }

  async function saveEmployee(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = {
        ...empForm,
        hire_date: empForm.hire_date || null,
        phone: empForm.phone || null,
        weekly_hours: Number(empForm.weekly_hours.replace(",", ".")) || 40,
      };
      if (editing) {
        await api(`/api/v1/employees/${editing.id}`, { method: "PATCH", body });
        toast.success("Trabajador actualizado", `${empForm.first_name} ${empForm.last_name}`);
      } else {
        await api("/api/v1/employees", { method: "POST", body });
        toast.success("Trabajador dado de alta", `${empForm.first_name} ${empForm.last_name}`);
      }
      setEmployeeOpen(false);
      employees.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/users", {
        method: "POST",
        body: {
          email: userForm.email,
          full_name: userForm.full_name,
          password: userForm.password,
          role_level: Number(userForm.role_level),
          employee_id: userForm.employee_id || null,
          must_change_password: userForm.must_change_password,
        },
      });
      toast.success("Usuario creado", `${userForm.email} · nivel ${userForm.role_level}`);
      setUserOpen(false);
      setUserForm({ email: "", full_name: "", password: "", role_level: "4", employee_id: "", must_change_password: true });
      users.reload();
      employees.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function resetPassword(event: React.FormEvent) {
    event.preventDefault();
    if (!resetUser) return;
    setBusy(true);
    try {
      await api(`/api/v1/users/${resetUser.id}/reset-password`, {
        method: "POST",
        body: { new_password: newPassword, must_change_password: true },
      });
      toast.success("Contraseña restablecida", "El usuario deberá cambiarla en su próximo acceso.");
      setResetUser(null);
      setNewPassword("");
      users.reload();
    } catch (err) {
      toast.error("No se pudo restablecer", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(account: UserAccount) {
    setBusy(true);
    try {
      await api(`/api/v1/users/${account.id}`, {
        method: "PATCH",
        body: { is_active: !account.is_active },
      });
      toast.success(account.is_active ? "Usuario desactivado" : "Usuario activado", account.email);
      users.reload();
    } catch (err) {
      toast.error("Operación rechazada", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const availableEmployees = useMemo(
    () => (employees.data?.items ?? []).filter((employee) => !employee.user_id),
    [employees.data],
  );

  return (
    <>
      <PageHeader
        eyebrow="Equipo"
        title="Personal y accesos"
        subtitle="Trabajadores con ficha y código QR, cuentas con nivel de autorización y separación estricta de permisos."
        actions={
          <>
            <button type="button" className="btn btn-ghost" onClick={employees.reload} disabled={employees.loading}>
              <IconRefresh /> Actualizar
            </button>
            {tab === "employees" && can("workers.write") ? (
              <button type="button" className="btn btn-primary" onClick={openCreateEmployee}>
                <IconPlus /> Nuevo trabajador
              </button>
            ) : null}
            {tab === "users" && can("users.manage") ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setError(null);
                  setUserOpen(true);
                }}
              >
                <IconPlus /> Nueva cuenta
              </button>
            ) : null}
          </>
        }
      />

      <div className="toolbar" style={{ marginBottom: 14 }}>
        <Tabs
          value={tab}
          onChange={(value) => setTab(value as Tab)}
          tabs={[
            { value: "employees", label: "Trabajadores" },
            { value: "users", label: "Cuentas de acceso", disabled: !can("users.manage") },
            { value: "roles", label: "Roles y permisos", disabled: !can("roles.manage") && user?.role_level !== 1 },
          ]}
        />
        <span className="spacer" />
        <span className="count-chip">{employees.data ? `${employees.data.total} trabajadores` : "—"}</span>
      </div>

      {tab === "employees" ? (
        <>
          <section className="card">
            <div className="toolbar">
              <SearchInput
                value={search}
                onChange={(value) => {
                  setSearch(value);
                  setOffset(0);
                }}
                placeholder="Buscar por nombre o código…"
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
                <option value="">Cualquier estado</option>
                <option value="active">Activo</option>
                <option value="leave">Baja temporal</option>
                <option value="inactive">Inactivo</option>
              </select>
              <span className="spacer" />
              {can("workers.read") ? (
                <Link
                  href={`/etiquetas?kind=employee&ids=${(employees.data?.items ?? []).map((e) => e.id).join(",")}`}
                  className="btn btn-sm btn-ghost"
                >
                  <IconPrint /> Etiquetas del listado ({(employees.data?.items ?? []).length})
                </Link>
              ) : null}
            </div>

            {employees.error ? (
              <div style={{ padding: 16 }}>
                <ErrorBlock message={employees.error} onRetry={employees.reload} />
              </div>
            ) : null}
            {employees.loading && !employees.data ? <LoadingBlock label="Cargando personal…" /> : null}
            {employees.data && employees.data.items.length === 0 ? (
              <EmptyState
                icon={<IconUsers />}
                title="Sin trabajadores"
                description="Da de alta al primer trabajador para poder asignarle tareas y una cuenta de acceso."
                action={
                  can("workers.write") ? (
                    <button type="button" className="btn btn-sm btn-primary" onClick={openCreateEmployee}>
                      Nuevo trabajador
                    </button>
                  ) : undefined
                }
              />
            ) : null}

            {employees.data && employees.data.items.length > 0 ? (
              <>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Código</th>
                        <th>Trabajador</th>
                        <th>Departamento</th>
                        <th>Puesto</th>
                        <th className="num">Jornada</th>
                        <th>Alta</th>
                        <th>Estado</th>
                        <th>Acceso</th>
                        <th className="actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {employees.data.items.map((employee) => {
                        const meta = employeeStatusMeta[employee.status] ?? { tone: "neutral", label: employee.status };
                        return (
                          <tr key={employee.id}>
                            <td className="mono">{employee.code}</td>
                            <td>
                              <div className="row" style={{ gap: 9 }}>
                                <span className="avatar">{initials(`${employee.first_name} ${employee.last_name}`)}</span>
                                <div>
                                  <div className="strong small">
                                    {employee.last_name}, {employee.first_name}
                                  </div>
                                  <div className="tiny text-muted">{employee.phone ?? "Sin teléfono"}</div>
                                </div>
                              </div>
                            </td>
                            <td className="small">{employee.department || "—"}</td>
                            <td className="small">{employee.position || "—"}</td>
                            <td className="num small">{employee.weekly_hours ?? "40"} h</td>
                            <td className="small nowrap">{employee.hire_date ? fmtDate(employee.hire_date) : "—"}</td>
                            <td><Badge tone={meta.tone as "success"}>{meta.label}</Badge></td>
                            <td>
                              {employee.user_id ? (
                                <Badge tone="accent">Con cuenta</Badge>
                              ) : (
                                <span className="small text-muted">Sin cuenta</span>
                              )}
                            </td>
                            <td className="actions">
                              <Link href={`/etiquetas?kind=employee&ids=${employee.id}`} className="btn btn-sm btn-ghost" title="Etiqueta QR">
                                <IconPrint />
                              </Link>
                              {can("workers.write") ? (
                                <button type="button" className="btn btn-sm btn-ghost" onClick={() => openEditEmployee(employee)}>
                                  Editar
                                </button>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <Pagination total={employees.data.total} limit={employees.data.limit} offset={employees.data.offset} onChange={setOffset} />
              </>
            ) : null}
          </section>

          <div className="alert" style={{ marginTop: 14 }}>
            <strong>Fichaje y turnos · Fase 7</strong>
            <span>
              El control horario, turnos y asignación de tareas se implementará con el módulo de reparto. La
              ficha del trabajador y su código QR de identificación ya son operativos.
            </span>
          </div>
        </>
      ) : null}

      {tab === "users" ? (
        <section className="card">
          {!can("users.manage") ? (
            <EmptyState icon={<IconKey />} title="Acceso restringido" description="Solo el administrador puede gestionar cuentas de acceso." />
          ) : (
            <>
              {users.error ? <div style={{ padding: 16 }}><ErrorBlock message={users.error} onRetry={users.reload} /></div> : null}
              {users.loading && !users.data ? <LoadingBlock label="Cargando cuentas…" /> : null}
              {users.data ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Usuario</th>
                        <th>Nivel</th>
                        <th>Trabajador</th>
                        <th>Último acceso</th>
                        <th>Estado</th>
                        <th className="actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {users.data.items.map((account) => (
                        <tr key={account.id}>
                          <td>
                            <div className="strong small">{account.full_name}</div>
                            <div className="tiny text-muted">{account.email}</div>
                          </td>
                          <td className="small">
                            {roleLevelLabel[account.role_level] ?? account.role_name}
                          </td>
                          <td className="small">
                            {account.employee ? `${account.employee.code} · ${account.employee.first_name} ${account.employee.last_name}` : "—"}
                          </td>
                          <td className="small text-muted nowrap">
                            {account.last_login_at ? fmtDateTime(account.last_login_at) : "Nunca"}
                          </td>
                          <td>
                            <div className="row" style={{ gap: 5 }}>
                              <Badge tone={account.is_active ? "success" : "neutral"}>
                                {account.is_active ? "Activa" : "Desactivada"}
                              </Badge>
                              {account.must_change_password ? <Badge tone="warning">Clave temporal</Badge> : null}
                            </div>
                          </td>
                          <td className="actions">
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => {
                                setResetUser(account);
                                setNewPassword("");
                              }}
                            >
                              <IconKey /> Clave
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => toggleActive(account)}
                              disabled={busy || account.id === user?.id}
                              title={account.id === user?.id ? "No puede desactivar su propia cuenta" : undefined}
                            >
                              {account.is_active ? "Desactivar" : "Activar"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </>
          )}
        </section>
      ) : null}

      {tab === "roles" ? (
        <div className="grid grid-2">
          {roles.loading && !roles.data ? <LoadingBlock /> : null}
          {roles.error ? <ErrorBlock message={roles.error} onRetry={roles.reload} /> : null}
          {roles.data?.map((role) => (
            <Card key={role.id}>
              <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
                <span className="strong">{role.name}</span>
                <Badge tone={role.level <= 2 ? "danger" : role.level === 3 ? "warning" : role.level === 5 ? "neutral" : "info"}>
                  Nivel {role.level}
                </Badge>
              </div>
              <p className="small text-muted">{role.description}</p>
            </Card>
          ))}
          <div className="alert warning" style={{ gridColumn: "1 / -1" }}>
            <strong>AURORA no puede autoconcederse permisos</strong>
            <span>
              Los permisos derivan del nivel del rol y se comprueban en el servidor. Ninguna cuenta puede
              elevar su propio nivel, modificarse a sí misma ni crear roles superiores al suyo.
            </span>
          </div>
        </div>
      ) : null}

      <Modal
        open={employeeOpen}
        title={editing ? "Editar trabajador" : "Nuevo trabajador"}
        subtitle={editing ? editing.code : "El código se asignará automáticamente"}
        onClose={() => setEmployeeOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setEmployeeOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="employee-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconCheck />} {editing ? "Guardar cambios" : "Dar de alta"}
            </button>
          </>
        }
      >
        <form id="employee-form" className="form-grid" onSubmit={saveEmployee}>
          <Field label="Nombre" required>
            <input className="input" value={empForm.first_name} onChange={(event) => setEmpForm({ ...empForm, first_name: event.target.value })} required />
          </Field>
          <Field label="Apellidos" required>
            <input className="input" value={empForm.last_name} onChange={(event) => setEmpForm({ ...empForm, last_name: event.target.value })} required />
          </Field>
          <Field label="Departamento">
            <input className="input" value={empForm.department} onChange={(event) => setEmpForm({ ...empForm, department: event.target.value })} placeholder="Almacén, Logística…" />
          </Field>
          <Field label="Puesto">
            <input className="input" value={empForm.position} onChange={(event) => setEmpForm({ ...empForm, position: event.target.value })} />
          </Field>
          <Field label="Fecha de alta">
            <input className="input" type="date" value={empForm.hire_date} onChange={(event) => setEmpForm({ ...empForm, hire_date: event.target.value })} />
          </Field>
          <Field label="Teléfono">
            <input className="input" value={empForm.phone} onChange={(event) => setEmpForm({ ...empForm, phone: event.target.value })} />
          </Field>
          <Field label="Jornada semanal" hint="Horas de contrato; base de la bolsa de horas">
            <input
              className="input"
              inputMode="decimal"
              value={empForm.weekly_hours}
              onChange={(event) => setEmpForm({ ...empForm, weekly_hours: event.target.value })}
            />
          </Field>
          <Field label="Estado" className="full">
            <select className="select" value={empForm.status} onChange={(event) => setEmpForm({ ...empForm, status: event.target.value })}>
              <option value="active">Activo</option>
              <option value="leave">Baja temporal</option>
              <option value="inactive">Inactivo</option>
            </select>
          </Field>
          <div className="full">{error ? <div className="form-error">{error}</div> : null}</div>
        </form>
      </Modal>

      <Modal
        open={userOpen}
        title="Nueva cuenta de acceso"
        subtitle="El nivel determina los permisos; verificado siempre en servidor"
        onClose={() => setUserOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setUserOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="user-form" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconPlus />} Crear cuenta
            </button>
          </>
        }
      >
        <form id="user-form" className="stack" onSubmit={createUser}>
          <div className="form-grid">
            <Field label="Nombre completo" required>
              <input className="input" value={userForm.full_name} onChange={(event) => setUserForm({ ...userForm, full_name: event.target.value })} required />
            </Field>
            <Field label="Correo electrónico" required>
              <input className="input" type="email" value={userForm.email} onChange={(event) => setUserForm({ ...userForm, email: event.target.value })} required />
            </Field>
            <Field label="Contraseña temporal" required hint="Mínimo 10 caracteres con letras y números.">
              <input
                className="input"
                type="text"
                value={userForm.password}
                onChange={(event) => setUserForm({ ...userForm, password: event.target.value })}
                minLength={10}
                required
              />
            </Field>
            <Field label="Nivel de autorización" required>
              <select className="select" value={userForm.role_level} onChange={(event) => setUserForm({ ...userForm, role_level: event.target.value })}>
                <option value="1">Nivel 1 · Administrador</option>
                <option value="2">Nivel 2 · Responsable de logística</option>
                <option value="3">Nivel 3 · Encargado</option>
                <option value="4">Nivel 4 · Trabajador</option>
                <option value="5">Nivel 5 · Auditor</option>
              </select>
            </Field>
            <Field label="Trabajador asociado" className="full" hint="Opcional. Solo se muestran fichas sin cuenta.">
              <select className="select" value={userForm.employee_id} onChange={(event) => setUserForm({ ...userForm, employee_id: event.target.value })}>
                <option value="">Sin trabajador</option>
                {availableEmployees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.code} · {employee.last_name}, {employee.first_name}
                  </option>
                ))}
              </select>
            </Field>
            <div className="full">
              <label className="check">
                <input
                  type="checkbox"
                  checked={userForm.must_change_password}
                  onChange={(event) => setUserForm({ ...userForm, must_change_password: event.target.checked })}
                />
                Obligar a cambiar la contraseña en el primer acceso
              </label>
            </div>
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <Modal
        open={Boolean(resetUser)}
        title="Restablecer contraseña"
        subtitle={resetUser?.email}
        onClose={() => setResetUser(null)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setResetUser(null)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" form="reset-form" className="btn btn-danger" disabled={busy}>
              {busy ? <span className="spinner" /> : <IconKey />} Restablecer
            </button>
          </>
        }
      >
        <form id="reset-form" className="stack" onSubmit={resetPassword}>
          <Field label="Nueva contraseña temporal" required>
            <input
              className="input"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              minLength={10}
              required
            />
          </Field>
          <div className="alert">
            <span>
              Se revocarán todas las sesiones activas del usuario y deberá establecer una nueva contraseña al
              entrar. La acción queda registrada en auditoría.
            </span>
          </div>
        </form>
      </Modal>
    </>
  );
}
