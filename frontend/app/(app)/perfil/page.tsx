"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, initials, roleLevelLabel } from "@/lib/format";
import { Badge, Card, Field, LoadingBlock, Modal, PageHeader, useToast } from "@/components/ui";
import { IconLock, IconLogout, IconShield } from "@/components/icons";

const PERMISSION_LABEL: Record<string, string> = {
  "inventory.read": "Consultar inventario",
  "inventory.write": "Crear y editar productos",
  "inventory.delete": "Desactivar productos",
  "locations.read": "Consultar almacenes y ubicaciones",
  "locations.write": "Gestionar ubicaciones",
  "pallets.read": "Consultar palés",
  "pallets.write": "Crear, llenar y mover palés",
  "movements.read": "Consultar movimientos",
  "movements.write": "Registrar movimientos",
  "movements.confirm": "Confirmar movimientos",
  "movements.cancel": "Cancelar borradores",
  "reservations.read": "Consultar reservas",
  "reservations.write": "Gestionar reservas",
  "invoices.read": "Consultar facturas",
  "invoices.write": "Subir facturas y líneas",
  "invoices.reconcile": "Conciliar facturas",
  "workers.read": "Consultar personal",
  "workers.write": "Gestionar personal",
  "attendance.read": "Consultar fichajes",
  "attendance.manage": "Gestionar fichajes",
  "deliveries.read": "Consultar repartos",
  "deliveries.write": "Gestionar repartos",
  "incidents.read": "Consultar incidencias",
  "incidents.write": "Gestionar incidencias",
  "reports.read": "Consultar informes",
  "reports.export": "Exportar informes",
  "audit.read": "Consultar auditoría",
  "users.manage": "Gestionar usuarios",
  "roles.manage": "Gestionar roles",
  "settings.manage": "Modificar configuración",
  "ai.use": "Usar AURORA Voice",
  "ai.approve_actions": "Aprobar acciones de IA",
  "calls.manage": "Gestionar llamadas",
};

function ProfileView() {
  const { user, can, refresh } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const forced = params.get("force") === "1" || Boolean(user?.must_change_password);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logoutAllOpen, setLogoutAllOpen] = useState(false);
  const [sessionTime, setSessionTime] = useState("—");

  useEffect(() => {
    setSessionTime(fmtDateTime(new Date().toISOString()));
  }, []);

  if (!user) return <LoadingBlock />;

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (next !== repeat) {
      setError("La nueva contraseña y su repetición no coinciden.");
      return;
    }
    setBusy(true);
    try {
      await api("/api/v1/auth/change-password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      toast.success("Contraseña actualizada", "El resto de sesiones se han cerrado.");
      setCurrent("");
      setNext("");
      setRepeat("");
      await refresh();
      if (forced) {
        router.replace("/");
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function logoutAll() {
    setBusy(true);
    try {
      await api("/api/v1/auth/logout-all", { method: "POST" });
      toast.success("Sesiones cerradas", "Deberás iniciar sesión de nuevo.");
      router.replace("/login");
    } catch (err) {
      toast.error("No se pudo cerrar la sesión", errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Cuenta"
        title="Mi perfil"
        subtitle="Datos de acceso, nivel de autorización y seguridad de la sesión."
        actions={
          can("inventory.read") ? (
            <Link href="/" className="btn btn-ghost">
              Volver al panel
            </Link>
          ) : undefined
        }
      />

      {forced ? (
        <div className="alert warning" style={{ marginBottom: 16 }}>
          <strong>Debe cambiar su contraseña</strong>
          <span>Su cuenta está marcada como contraseña temporal. Cambie la clave para continuar operando.</span>
        </div>
      ) : null}

      <div className="split">
        <div className="stack">
          <Card title="Seguridad de la cuenta">
            <form onSubmit={changePassword} className="stack">
              <div className="form-grid">
                <Field label="Contraseña actual" required className="full">
                  <input
                    className="input"
                    type="password"
                    autoComplete="current-password"
                    value={current}
                    onChange={(event) => setCurrent(event.target.value)}
                    required
                  />
                </Field>
                <Field label="Nueva contraseña" required hint="Mínimo 10 caracteres con letras y números.">
                  <input
                    className="input"
                    type="password"
                    autoComplete="new-password"
                    value={next}
                    onChange={(event) => setNext(event.target.value)}
                    minLength={10}
                    required
                  />
                </Field>
                <Field label="Repetir nueva contraseña" required>
                  <input
                    className="input"
                    type="password"
                    autoComplete="new-password"
                    value={repeat}
                    onChange={(event) => setRepeat(event.target.value)}
                    minLength={10}
                    required
                  />
                </Field>
              </div>
              {error ? <div className="form-error">{error}</div> : null}
              <div className="row" style={{ justifyContent: "space-between" }}>
                <button type="button" className="btn btn-ghost" onClick={() => setLogoutAllOpen(true)}>
                  <IconLogout /> Cerrar todas las sesiones
                </button>
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  {busy ? <span className="spinner" /> : <IconLock />} Actualizar contraseña
                </button>
              </div>
            </form>
          </Card>

          <Card title="Permisos efectivos" subtitle="Comprobados en el servidor en cada operación">
            <div className="row" style={{ gap: 6 }}>
              {user.permissions.map((permission) => (
                <span className="tag-pill" key={permission}>
                  {PERMISSION_LABEL[permission] ?? permission}
                </span>
              ))}
            </div>
            {!user.permissions.length ? <p className="small text-muted">Sin permisos asignados.</p> : null}
          </Card>
        </div>

        <div className="side-panel">
          <Card title="Identidad">
            <div className="row" style={{ gap: 12, marginBottom: 12 }}>
              <span className="avatar lg">{initials(user.full_name)}</span>
              <div>
                <div className="strong">{user.full_name}</div>
                <div className="small text-muted">{user.email}</div>
              </div>
            </div>
            <dl className="def-list">
              <div className="def-row">
                <dt>Nivel</dt>
                <dd>{roleLevelLabel[user.role_level] ?? user.role_name}</dd>
              </div>
              <div className="def-row">
                <dt>Rol</dt>
                <dd>{user.role_name}</dd>
              </div>
              {user.employee ? (
                <>
                  <div className="def-row">
                    <dt>Código</dt>
                    <dd className="mono">{user.employee.code}</dd>
                  </div>
                  <div className="def-row">
                    <dt>Departamento</dt>
                    <dd>{user.employee.department || "—"}</dd>
                  </div>
                  <div className="def-row">
                    <dt>Puesto</dt>
                    <dd>{user.employee.position || "—"}</dd>
                  </div>
                </>
              ) : (
                <div className="def-row">
                  <dt>Ficha</dt>
                  <dd>Sin trabajador asociado</dd>
                </div>
              )}
              <div className="def-row">
                <dt>Contraseña</dt>
                <dd>
                  {user.must_change_password ? (
                    <Badge tone="warning">Temporal</Badge>
                  ) : (
                    <Badge tone="success">Actualizada</Badge>
                  )}
                </dd>
              </div>
            </dl>
          </Card>

          <div className="alert">
            <strong><IconShield width={14} height={14} style={{ display: "inline", verticalAlign: "-2px" }} /> Sesión</strong>
            <span>
              Sesión emitida a las <span suppressHydrationWarning>{sessionTime}</span> (hora de Madrid). El
              identificador de sesión se revoca al cerrar sesión o al cambiar la contraseña.
            </span>
          </div>
        </div>
      </div>

      <Modal
        open={logoutAllOpen}
        title="Cerrar todas las sesiones"
        onClose={() => setLogoutAllOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setLogoutAllOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="button" className="btn btn-danger" onClick={logoutAll} disabled={busy}>
              {busy ? <span className="spinner" /> : null} Cerrar todas
            </button>
          </>
        }
      >
        <p className="text-soft small">
          Se revocarán todas las sesiones activas en todos los dispositivos y se incrementará la versión de
          seguridad de la cuenta. Deberá iniciar sesión de nuevo.
        </p>
      </Modal>
    </>
  );
}

export default function ProfilePage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <ProfileView />
    </Suspense>
  );
}
