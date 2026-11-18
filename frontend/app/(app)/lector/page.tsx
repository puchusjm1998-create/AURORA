"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { tokenFromMessage, webNfcSupported } from "@/lib/nfc";
import type { NfcTapResult } from "@/lib/types";
import { Badge, Field, PageHeader, useToast } from "@/components/ui";
import { IconNfc, IconRefresh } from "@/components/icons";

type NfcAction = "auto" | "clock_in" | "clock_out" | "break_start" | "break_end";
type ReaderState = "idle" | "scanning" | "unsupported";

const ACTIONS: { value: NfcAction; label: string }[] = [
  { value: "auto", label: "Automático (alterna entrada/salida/pausa)" },
  { value: "clock_in", label: "Entrada" },
  { value: "clock_out", label: "Salida" },
  { value: "break_start", label: "Iniciar pausa" },
  { value: "break_end", label: "Finalizar pausa" },
];

const RESULT_TONE: Record<string, "success" | "info" | "warning"> = {
  clock_in: "success",
  clock_out: "info",
  break_start: "warning",
  break_end: "success",
};

const STATE_LABEL: Record<string, string> = {
  in: "Dentro",
  out: "Fuera",
  break: "En pausa",
};

export default function NfcReaderPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [supported, setSupported] = useState(false);
  const [readerState, setReaderState] = useState<ReaderState>("idle");
  const [action, setAction] = useState<NfcAction>("auto");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<NfcTapResult | null>(null);
  const [history, setHistory] = useState<NfcTapResult[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const readerRef = useRef<NDEFReader | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const lastTapRef = useRef({ token: "", at: 0 });
  const actionRef = useRef<NfcAction>("auto");
  const busyRef = useRef(false);

  useEffect(() => {
    actionRef.current = action;
  }, [action]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    setSupported(webNfcSupported());
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
      readerRef.current = null;
    };
  }, []);

  useEffect(() => {
    // El teclado virtual de Android estorba al leer con Web NFC; solo se enfoca
    // automáticamente con puntero fino (lector USB en escritorio).
    if (!window.matchMedia?.("(pointer: fine)").matches) return;
    const focus = window.setTimeout(() => inputRef.current?.focus(), 120);
    return () => window.clearTimeout(focus);
  }, []);

  async function submitToken(raw: string, source: "webnfc" | "hid" | "manual") {
    const clean = raw.trim();
    if (!clean || busyRef.current) return;
    if (!clean.startsWith("AUR-NFC-") || clean.length < 16) {
      setError("El código leído no es un token AURORA válido.");
      return;
    }
    const now = Date.now();
    if (lastTapRef.current.token === clean && now - lastTapRef.current.at < 5000) {
      return;
    }
    lastTapRef.current = { token: clean, at: now };
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await api<NfcTapResult>("/api/v1/nfc/tap", {
        method: "POST",
        body: { token: clean, action: actionRef.current, note: `Lector ${source}` },
      });
      setResult(response);
      setHistory((items) => [response, ...items].slice(0, 6));
      setToken("");
      navigator.vibrate?.(70);
      toast.success(response.event_label, response.message);
      if (window.matchMedia?.("(pointer: fine)").matches) {
        window.setTimeout(() => inputRef.current?.focus(), 80);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function startWebNfc() {
    if (!supported) {
      setError(
        "Web NFC no está disponible. Use Chrome para Android sobre HTTPS o un lector USB en modo teclado.",
      );
      setReaderState("unsupported");
      return;
    }
    if (readerState === "scanning") return;
    setError(null);
    try {
      const reader = new NDEFReader();
      const controller = new AbortController();
      reader.onreading = (event) => {
        const read = tokenFromMessage(event.message);
        if (!read) {
          setError(
            "La etiqueta no contiene un token AURORA. Grabe la tarjeta desde «Tarjetas NFC».",
          );
          return;
        }
        void submitToken(read, "webnfc");
      };
      reader.onreadingerror = () => {
        setError("No se pudo leer la etiqueta. Acérquela de nuevo y manténgala unos segundos.");
      };
      await reader.scan({ signal: controller.signal });
      readerRef.current = reader;
      controllerRef.current = controller;
      setReaderState("scanning");
    } catch (err) {
      setReaderState("unsupported");
      setError(
        err instanceof Error && err.name === "NotAllowedError"
          ? "Permiso NFC denegado. Actívelo en el navegador o use el lector USB."
          : "No se pudo iniciar Web NFC en este dispositivo. Use el lector USB.",
      );
    }
  }

  function stopWebNfc() {
    controllerRef.current?.abort();
    controllerRef.current = null;
    readerRef.current = null;
    setReaderState("idle");
  }

  return (
    <>
      <PageHeader
        eyebrow="Fichaje"
        title="Lector de tarjetas NFC"
        subtitle="Fichaje real con la tarjeta del trabajador: Web NFC del navegador, lector USB en modo teclado o entrada manual del token."
        actions={
          can("attendance.manage") ? (
            <Link className="btn btn-ghost" href="/tarjetas">
              Gestionar tarjetas
            </Link>
          ) : null
        }
      />

      <div className="alert info" style={{ marginBottom: 16 }}>
        <span>
          Web NFC funciona en Chrome para Android sobre HTTPS (o localhost) y requiere una etiqueta
          NDEF con el token de AURORA. En ordenador puede usar un lector USB que escriba el token
          como teclado y pulse Enter. Ningún dato de la tarjeta se guarda en el navegador.
        </span>
      </div>

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <section className="card">
          <div className="card-body">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <div className="eyebrow">
                  <IconNfc /> Lector
                </div>
                <div className="small text-muted">
                  Estado:{" "}
                  {readerState === "scanning"
                    ? "Web NFC escuchando etiquetas"
                    : readerState === "unsupported"
                      ? "Web NFC no disponible; use USB"
                      : supported
                        ? "Listo para activar Web NFC"
                        : "Web NFC no compatible con este navegador"}
                </div>
              </div>
              <Badge tone={readerState === "scanning" ? "success" : "info"}>
                {readerState === "scanning" ? "Activo" : supported ? "Compatible" : "USB / manual"}
              </Badge>
            </div>

            <div className="row" style={{ marginTop: 14, flexWrap: "wrap" }}>
              {readerState !== "scanning" ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={startWebNfc}
                  disabled={!supported}
                >
                  <IconNfc /> Activar lector NFC
                </button>
              ) : (
                <button type="button" className="btn btn-ghost" onClick={stopWebNfc}>
                  Detener lector NFC
                </button>
              )}
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setResult(null);
                  setError(null);
                  inputRef.current?.focus();
                }}
              >
                <IconRefresh /> Nueva lectura
              </button>
            </div>

            <div style={{ marginTop: 16 }}>
              <Field label="Acción al leer" hint="Automático usa el estado real del fichaje del día">
                <select
                  className="select"
                  value={action}
                  onChange={(event) => setAction(event.target.value as NfcAction)}
                >
                  {ACTIONS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submitToken(token, "hid");
              }}
              style={{ marginTop: 16 }}
            >
              <Field
                label="Token de la tarjeta"
                hint="El lector USB lo escribe aquí; también puede pegarlo con cuidado"
              >
                <input
                  ref={inputRef}
                  className="input mono"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void submitToken(token, "hid");
                    }
                  }}
                  placeholder="AUR-NFC-…"
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  disabled={busy}
                />
              </Field>
              <button
                type="submit"
                className="btn btn-primary"
                style={{ marginTop: 12 }}
                disabled={busy || token.trim().length === 0}
              >
                {busy ? <span className="spinner" /> : <IconNfc />} Registrar fichaje
              </button>
            </form>

            {error ? (
              <div className="alert danger" style={{ marginTop: 14 }}>
                <span>{error}</span>
              </div>
            ) : null}
          </div>
        </section>

        <section className="card">
          <div className="card-body">
            <div className="eyebrow">Resultado</div>
            {result ? (
              <>
                <div
                  className={`alert ${RESULT_TONE[result.event_type] ?? "success"}`}
                  style={{ marginTop: 12 }}
                >
                  <strong>{result.message}</strong>
                  <span>
                    {result.employee.first_name} {result.employee.last_name} ·{" "}
                    {result.employee.code} · {fmtDateTime(result.occurred_at)}
                  </span>
                </div>
                <div className="grid grid-2" style={{ marginTop: 12 }}>
                  <div className="kpi">
                    <span className="kpi-label">Evento</span>
                    <div className="strong small" style={{ marginTop: 6 }}>
                      {result.event_label}
                    </div>
                    <span className="kpi-meta">{result.card_label}</span>
                  </div>
                  <div className="kpi">
                    <span className="kpi-label">Estado tras la lectura</span>
                    <div className="kpi-value" style={{ fontSize: 22 }}>
                      {STATE_LABEL[result.state] ?? result.state}
                    </div>
                    <span className="kpi-meta">{fmtDateTime(result.occurred_at)}</span>
                  </div>
                </div>
              </>
            ) : (
              <div className="empty" style={{ marginTop: 12 }}>
                <div className="empty-icon">
                  <IconNfc width={26} height={26} />
                </div>
                <div className="strong">Esperando una tarjeta</div>
                <p className="small text-muted">
                  Active Web NFC y acerque la etiqueta, o deje que el lector USB escriba el token y
                  pulse Enter.
                </p>
              </div>
            )}

            {history.length > 0 ? (
              <div style={{ marginTop: 18 }}>
                <div className="tiny text-muted" style={{ marginBottom: 6 }}>
                  Lecturas de esta sesión
                </div>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Hora</th>
                        <th>Trabajador</th>
                        <th>Evento</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((item, index) => (
                        <tr key={`${item.occurred_at}-${index}`}>
                          <td className="small nowrap">{fmtDateTime(item.occurred_at)}</td>
                          <td className="small">
                            {item.employee.first_name} {item.employee.last_name}
                          </td>
                          <td className="small">{item.event_label}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </>
  );
}
