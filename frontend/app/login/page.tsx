"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { IconAlert, IconQr } from "@/components/icons";

function LoginForm() {
  const { user, loading, login, system } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const next = params.get("next") || "/";

  useEffect(() => {
    if (!loading && user) {
      router.replace(user.must_change_password ? "/perfil?force=1" : next);
    }
  }, [loading, user, next, router]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const me = await login(email.trim(), password);
      router.replace(me.must_change_password ? "/perfil?force=1" : next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const fillDemo = (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword("Aurora2026!");
    setError(null);
  };

  return (
    <div className="login-page">
      <section className="login-visual">
        <div className="brand">
          <span className="brand-mark">
            <IconQr width={22} height={22} />
          </span>
          <span>
            <span className="brand-name">AURORA</span>
            <span className="brand-sub">Logistics AI</span>
          </span>
        </div>

        <div className="login-hero">
          <span className="eyebrow">Project Aurora · Fase 1</span>
          <h1>
            El centro de inteligencia de tu <em>almacén</em>.
          </h1>
          <p>
            Inventario en tiempo real, trazabilidad QR de palés y objetos, movimientos auditados y
            localización exacta de cada referencia. Diseñado para almacenes de 10 a 50 personas.
          </p>
          <div className="login-points">
            <div className="login-point">
              <i>01</i>
              <span>Existencias físicas, reservadas, disponibles y en tránsito, siempre cuadradas.</span>
            </div>
            <div className="login-point">
              <i>02</i>
              <span>Lectura QR desde el móvil y etiquetas imprimibles para cada ubicación y palé.</span>
            </div>
            <div className="login-point">
              <i>03</i>
              <span>Permisos por niveles comprobados en el servidor y auditoría inalterable.</span>
            </div>
          </div>
        </div>

        <p className="tiny text-muted">
          Almacenamiento UTC · visualización Europe/Madrid · infraestructura preparada para la UE
        </p>
      </section>

      <section className="login-form-side">
        <form className="login-card" onSubmit={onSubmit}>
          <div>
            <h2>Iniciar sesión</h2>
            <p className="sub">Accede con las credenciales de tu tarjeta digital de trabajador.</p>
          </div>

          {system?.demo_mode ? (
            <div className="demo-box">
              <b>Entorno de demostración</b>
              <span>
                Datos ficticios aislados de producción. Cuentas de prueba con contraseña{" "}
                <code className="inline-code">Aurora2026!</code>
              </span>
              <span style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button type="button" onClick={() => fillDemo("admin@aurora.demo")}>
                  Administrador
                </button>
                <button type="button" onClick={() => fillDemo("operario@aurora.demo")}>
                  Operario
                </button>
                <button type="button" onClick={() => fillDemo("auditor@aurora.demo")}>
                  Auditor
                </button>
              </span>
            </div>
          ) : null}

          {error ? (
            <div className="form-error" role="alert">
              {error}
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="email">Correo electrónico</label>
            <input
              id="email"
              className="input input-lg"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="nombre@empresa.es"
              required
              autoFocus
            />
          </div>

          <div className="field">
            <label htmlFor="password">Contraseña</label>
            <div style={{ position: "relative" }}>
              <input
                id="password"
                className="input input-lg"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••••"
                required
                style={{ paddingRight: 76 }}
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                style={{
                  position: "absolute",
                  right: 6,
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "none",
                  border: 0,
                  color: "var(--muted)",
                  fontSize: 11.5,
                  cursor: "pointer",
                  padding: "6px 8px",
                }}
              >
                {showPassword ? "Ocultar" : "Mostrar"}
              </button>
            </div>
          </div>

          <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
            {busy ? <span className="spinner" /> : null}
            {busy ? "Verificando…" : "Entrar en AURORA"}
          </button>

          <p className="login-legal">
            <IconAlert width={12} height={12} style={{ display: "inline", verticalAlign: "-2px" }} /> El acceso
            queda registrado en la auditoría del sistema.
          </p>
        </form>
      </section>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="center-spin"><div className="spinner" /></div>}>
      <LoginForm />
    </Suspense>
  );
}
