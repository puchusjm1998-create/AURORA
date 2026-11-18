"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { fmtRelative, initials, roleLevelLabel } from "@/lib/format";
import {
  IconActivity,
  IconAlert,
  IconBox,
  IconCamera,
  IconClock,
  IconClose,
  IconDashboard,
  IconIncident,
  IconInvoice,
  IconLogout,
  IconMenu,
  IconMic,
  IconMovements,
  IconNfc,
  IconPallet,
  IconPhone,
  IconPin,
  IconQr,
  IconReports,
  IconReserve,
  IconRoute,
  IconScan,
  IconTask,
  IconTruck,
  IconShield,
  IconUsers,
  IconWarehouse,
} from "./icons";

interface NavEntry {
  href: string;
  label: string;
  permission?: string;
  icon: React.ReactNode;
  group: string;
  exact?: boolean;
  match?: string;
}

const NAV: NavEntry[] = [
  { href: "/", label: "Panel", permission: "inventory.read", icon: <IconDashboard />, group: "Operación", exact: true },
  { href: "/escaner", label: "Escanear QR", permission: "inventory.read", icon: <IconScan />, group: "Operación" },
  { href: "/operaciones", label: "Operaciones", permission: "movements.write", icon: <IconActivity />, group: "Operación" },
  { href: "/tareas", label: "Tareas", permission: "tasks.read", icon: <IconTask />, group: "Operación" },
  { href: "/incidencias", label: "Incidencias", permission: "incidents.read", icon: <IconIncident />, group: "Operación" },
  { href: "/alertas", label: "Alertas", permission: "incidents.read", icon: <IconAlert />, group: "Operación" },
  { href: "/voz", label: "AURORA Voice", permission: "inventory.read", icon: <IconMic />, group: "Operación" },
  { href: "/optimizacion", label: "Optimización", permission: "inventory.read", icon: <IconRoute />, group: "Operación" },
  { href: "/fichaje", label: "Fichaje", permission: "attendance.clock", icon: <IconClock />, group: "Operación" },
  { href: "/lector", label: "Lector NFC", permission: "attendance.clock", icon: <IconNfc />, group: "Operación", exact: true },
  { href: "/inventario", label: "Inventario", permission: "inventory.read", icon: <IconBox />, group: "Inventario", match: "/producto" },
  { href: "/pales", label: "Palés", permission: "pallets.read", icon: <IconPallet />, group: "Inventario", match: "/pale" },
  { href: "/almacenes", label: "Almacén", permission: "locations.read", icon: <IconWarehouse />, group: "Inventario", match: "/almacen" },
  { href: "/reservas", label: "Reservas", permission: "reservations.read", icon: <IconReserve />, group: "Inventario" },
  { href: "/repartos", label: "Repartos", permission: "deliveries.read", icon: <IconTruck />, group: "Inventario", match: "/reparto" },
  { href: "/mi-reparto", label: "Mi reparto", permission: "deliveries.track", icon: <IconPin />, group: "Operación", exact: true },
  { href: "/movimientos", label: "Movimientos", permission: "movements.read", icon: <IconMovements />, group: "Inventario" },
  { href: "/facturas", label: "Facturas", permission: "invoices.read", icon: <IconInvoice />, group: "Gestión", match: "/factura" },
  { href: "/informes", label: "Informes", permission: "reports.read", icon: <IconReports />, group: "Gestión" },
  { href: "/personal", label: "Personal", permission: "workers.read", icon: <IconUsers />, group: "Gestión" },
  { href: "/turnos", label: "Turnos", permission: "workers.read", icon: <IconClock />, group: "Gestión" },
  { href: "/llamadas", label: "Llamadas", permission: "calls.manage", icon: <IconPhone />, group: "Gestión" },
  { href: "/tarjetas", label: "Tarjetas NFC", permission: "attendance.manage", icon: <IconQr />, group: "Gestión" },
  { href: "/bolsa-horas", label: "Bolsa de horas", permission: "attendance.read", icon: <IconClock />, group: "Gestión" },
  { href: "/auditoria", label: "Auditoría", permission: "audit.read", icon: <IconShield />, group: "Gestión" },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname() || "/";
  const { can } = useAuth();
  const groups = useMemo(() => {
    const visible = NAV.filter((item) => !item.permission || can(item.permission));
    return Array.from(new Set(visible.map((item) => item.group))).map((group) => ({
      group,
      items: visible.filter((item) => item.group === group),
    }));
  }, [can]);

  return (
    <>
      {groups.map(({ group, items }) => (
        <nav className="nav-group" key={group} aria-label={group}>
          <span className="nav-label">{group}</span>
          {items.map((item) => {
            const active = item.exact
              ? pathname === item.href
              : pathname.startsWith(item.href) || (item.match ? pathname.startsWith(item.match) : false);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-item${active ? " active" : ""}`}
                onClick={onNavigate}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      ))}
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout, system } = useAuth();
  const pathname = usePathname() || "/";
  const router = useRouter();
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      router.replace(`/login?next=${next}`);
      return;
    }
    if (user.must_change_password && pathname !== "/perfil") {
      router.replace("/perfil?force=1");
    }
  }, [loading, user, pathname, router]);

  useEffect(() => {
    setDrawer(false);
  }, [pathname]);

  const current = NAV.find((item) =>
    item.exact
      ? pathname === item.href
      : pathname.startsWith(item.href) || (item.match ? pathname.startsWith(item.match) : false),
  );

  if (loading) {
    return (
      <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}>
        <div style={{ display: "grid", gap: 12, justifyItems: "center" }}>
          <div className="brand-mark" aria-hidden="true">
            <IconQr width={22} height={22} />
          </div>
          <span className="small text-muted">Conectando con AURORA…</span>
          <div className="loading-bar" style={{ width: 160 }} />
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}>
        <span className="small text-muted">Redirigiendo al inicio de sesión…</span>
      </div>
    );
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="AURORA Logistics AI">
          <span className="brand-mark">
            <IconQr width={22} height={22} />
          </span>
          <span>
            <span className="brand-name">AURORA</span>
            <span className="brand-sub">Logistics AI</span>
          </span>
        </Link>

        <NavList />

        <div className="sidebar-footer">
          <div className="voice-card">
            <strong>AURORA Voice</strong>
            Asistente por voz en español.
            <span className="tag">En desarrollo · Fase 5</span>
          </div>
          <Link href="/perfil" className="user-chip">
            <span className="avatar">{initials(user.full_name)}</span>
            <span style={{ minWidth: 0, flex: 1 }}>
              <span className="user-name">{user.full_name}</span>
              <span className="user-role">{roleLevelLabel[user.role_level] ?? user.role_name}</span>
            </span>
          </Link>
          <div className="row tight">
            <Link href="/sistema" className="btn btn-sm btn-ghost" style={{ flex: 1 }}>
              <IconAlert /> Sistema
            </Link>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={async () => {
                await logout();
                router.replace("/login");
              }}
              aria-label="Cerrar sesión"
            >
              <IconLogout /> Salir
            </button>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="icon-btn mobile-only"
            aria-label="Abrir menú"
            onClick={() => setDrawer(true)}
          >
            <IconMenu />
          </button>
          <div className="topbar-title">
            <span className="crumb">AURORA Logistics AI</span>
            <span className="here">{current?.label ?? "AURORA"}</span>
          </div>
          <span className="topbar-spacer" />
          {system?.demo_mode ? <span className="demo-chip">Demo</span> : null}
          <div className="topbar-actions">
            <Link href="/escaner" className="icon-btn" aria-label="Escanear código QR" title="Escanear QR">
              <IconCamera />
            </Link>
            <Link href="/perfil" className="icon-btn desktop-only" aria-label="Mi perfil" title="Mi perfil">
              <span className="avatar" style={{ width: 26, height: 26, borderRadius: 8, fontSize: 10 }}>
                {initials(user.full_name)}
              </span>
            </Link>
          </div>
        </header>

        <main className="content">{children}</main>
      </div>

      <nav className="bottom-nav" aria-label="Navegación principal">
        <Link href="/" className={pathname === "/" ? "active" : ""}>
          <IconDashboard />
          Panel
        </Link>
        <Link href="/inventario" className={pathname.startsWith("/inventario") || pathname.startsWith("/producto") ? "active" : ""}>
          <IconBox />
          Stock
        </Link>
        <Link href="/escaner" className={pathname.startsWith("/escaner") ? "active" : ""} aria-label="Escanear QR">
          <span className="scan-fab">
            <IconScan />
          </span>
        </Link>
        <Link href="/pales" className={pathname.startsWith("/pales") || pathname.startsWith("/pale") ? "active" : ""}>
          <IconPallet />
          Palés
        </Link>
        <button type="button" onClick={() => setDrawer(true)} style={{ background: "none", border: 0, color: "var(--muted)" }}>
          <span style={{ display: "grid", justifyItems: "center", gap: 3 }}>
            <IconMenu />
            <span style={{ fontSize: 10, fontWeight: 600 }}>Más</span>
          </span>
        </button>
      </nav>

      {drawer ? (
        <>
          <div className="drawer-backdrop" onClick={() => setDrawer(false)} role="presentation" />
          <aside className="sidebar drawer" aria-label="Menú">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="brand" style={{ padding: 0 }}>
                <span className="brand-mark">
                  <IconQr width={22} height={22} />
                </span>
                <span>
                  <span className="brand-name">AURORA</span>
                  <span className="brand-sub">Logistics AI</span>
                </span>
              </span>
              <button type="button" className="icon-btn" onClick={() => setDrawer(false)} aria-label="Cerrar menú">
                <IconClose />
              </button>
            </div>
            <NavList onNavigate={() => setDrawer(false)} />
            <div className="sidebar-footer">
              <Link href="/sistema" className="nav-item" onClick={() => setDrawer(false)}>
                <IconAlert /> Sistema
              </Link>
              <Link href="/perfil" className="nav-item" onClick={() => setDrawer(false)}>
                <IconUsers /> Mi perfil
              </Link>
              <div className="voice-card">
                <strong>AURORA Voice</strong>
                Asistente por voz en español.
                <span className="tag">En desarrollo · Fase 5</span>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-block"
                onClick={async () => {
                  await logout();
                  router.replace("/login");
                }}
              >
                <IconLogout /> Cerrar sesión
              </button>
              <span className="tiny text-muted">
                Sesión iniciada {user.email} · última actividad {fmtRelative(new Date().toISOString())}
              </span>
            </div>
          </aside>
        </>
      ) : null}
    </div>
  );
}
