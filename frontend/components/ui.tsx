"use client";

import Link from "next/link";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { qrUrl } from "@/lib/api";
import { IconAlert, IconCheck, IconClose, IconRefresh, IconSearch } from "./icons";

/* ------------------------------------------------------------------ */
/* Page header                                                         */
/* ------------------------------------------------------------------ */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="page-head">
      <div className="page-head-copy">
        {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
        <h1 className="page-title">{title}</h1>
        {subtitle ? <p className="page-sub">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-head-actions">{actions}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Cards / badges                                                      */
/* ------------------------------------------------------------------ */
export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  flush = false,
}: {
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {title ? (
        <header className="card-head">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p className="sub">{subtitle}</p> : null}
          </div>
          {actions ? (
            <>
              <span className="spacer" />
              {actions}
            </>
          ) : null}
        </header>
      ) : null}
      <div className={flush ? "card-body flush" : "card-body"}>{children}</div>
    </section>
  );
}

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

export function Badge({
  tone = "neutral",
  children,
  dot = true,
}: {
  tone?: BadgeTone;
  children: React.ReactNode;
  dot?: boolean;
}) {
  return <span className={`badge ${tone}${dot ? "" : " no-dot"}`}>{children}</span>;
}

/* ------------------------------------------------------------------ */
/* Form helpers                                                        */
/* ------------------------------------------------------------------ */
export function Field({
  label,
  hint,
  required,
  children,
  className = "",
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`field ${className}`}>
      <label>
        {label} {required ? <span className="req">*</span> : null}
      </label>
      {children}
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder = "Buscar…",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="search-wrap">
      <IconSearch />
      <input
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        type="search"
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Empty / loading / error                                             */
/* ------------------------------------------------------------------ */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      {icon ?? <IconSearch />}
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action}
    </div>
  );
}

export function LoadingBlock({ label = "Cargando datos…" }: { label?: string }) {
  return (
    <div className="center-spin" role="status" aria-live="polite">
      <div style={{ display: "grid", gap: 10, justifyItems: "center" }}>
        <div className="spinner" />
        <span className="small text-muted">{label}</span>
      </div>
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="alert danger" role="alert">
      <strong>No se han podido cargar los datos</strong>
      <span>{message}</span>
      {onRetry ? (
        <div style={{ marginTop: 6 }}>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onRetry}>
            <IconRefresh /> Reintentar
          </button>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Modal                                                               */
/* ------------------------------------------------------------------ */
export function Modal({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide = false,
  closeOnBackdrop = true,
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
  closeOnBackdrop?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="modal-backdrop"
      onClick={closeOnBackdrop ? onClose : undefined}
      role="presentation"
    >
      <div
        className={`modal${wide ? " wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-head">
          <div style={{ flex: 1 }}>
            <h3>{title}</h3>
            {subtitle ? <p className="sub">{subtitle}</p> : null}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Cerrar">
            <IconClose />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-foot">{footer}</footer> : null}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirmar",
  danger = false,
  busy = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button
            type="button"
            className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? <span className="spinner" /> : null}
            {confirmLabel}
          </button>
        </>
      }
    >
      <p className="text-soft" style={{ fontSize: 13.5 }}>
        {message}
      </p>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Toasts                                                              */
/* ------------------------------------------------------------------ */
type ToastTone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  message?: string;
}

interface ToastApi {
  push: (tone: ToastTone, title: string, message?: string) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const remove = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const push = useCallback(
    (tone: ToastTone, title: string, message?: string) => {
      const id = ++counter.current;
      setItems((current) => [...current.slice(-3), { id, tone, title, message }]);
      setTimeout(() => remove(id), tone === "error" ? 8000 : 5000);
    },
    [remove],
  );

  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (title, message) => push("success", title, message),
      error: (title, message) => push("error", title, message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite" aria-atomic="false">
        {items.map((item) => (
          <div key={item.id} className={`toast ${item.tone}`} role="status">
            <span style={{ color: item.tone === "success" ? "var(--success)" : item.tone === "error" ? "var(--danger)" : "var(--info)" }}>
              {item.tone === "success" ? <IconCheck /> : <IconAlert />}
            </span>
            <div style={{ flex: 1 }}>
              <strong>{item.title}</strong>
              {item.message ? <span>{item.message}</span> : null}
            </div>
            <button type="button" className="x" onClick={() => remove(item.id)} aria-label="Cerrar aviso">
              <IconClose width={14} height={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}

/* ------------------------------------------------------------------ */
/* Pagination                                                          */
/* ------------------------------------------------------------------ */
export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="card-foot" style={{ justifyContent: "space-between" }}>
      <span className="small text-muted">
        Mostrando {from}–{to} de {total}
      </span>
      <div className="row tight">
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
        >
          Anterior
        </button>
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => onChange(offset + limit)}
          disabled={offset + limit >= total}
        >
          Siguiente
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* QR preview                                                          */
/* ------------------------------------------------------------------ */
export function QrImage({
  payload,
  size = 148,
  alt = "Código QR",
}: {
  payload: string;
  size?: number;
  alt?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={qrUrl(payload, 6)}
      alt={alt}
      width={size}
      height={size}
      style={{ width: size, height: size, background: "#fff", borderRadius: 8 }}
    />
  );
}

export function QrPreview({ payload, code }: { payload: string; code?: string }) {
  return (
    <div className="qr-preview">
      <QrImage payload={payload} />
      {code ? <span>{code}</span> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Misc                                                                */
/* ------------------------------------------------------------------ */
export function CopyButton({ value, label = "Copiar" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-sm btn-ghost"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          /* clipboard may be blocked in iframes */
        }
      }}
    >
      {copied ? <IconCheck /> : null}
      {copied ? "Copiado" : label}
    </button>
  );
}

export function Stat({
  label,
  value,
  meta,
  accent = false,
}: {
  label: string;
  value: React.ReactNode;
  meta?: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <div className={`kpi${accent ? " kpi-accent" : ""}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {meta ? <span className="kpi-meta">{meta}</span> : null}
    </div>
  );
}

export function PageLink({ href, className, children }: { href: string; className?: string; children: React.ReactNode }) {
  return (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: string; count?: number; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          aria-selected={value === tab.value}
          className={`tab${value === tab.value ? " active" : ""}`}
          disabled={tab.disabled}
          title={tab.disabled ? "Su perfil no tiene este permiso" : undefined}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
          {typeof tab.count === "number" ? <span className="text-muted"> · {tab.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
