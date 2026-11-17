"use client";

import jsQR from "jsqr";
import { useCallback, useEffect, useRef, useState } from "react";
import { IconCamera } from "./icons";

type ScannerState = "idle" | "starting" | "active" | "error";

export function QrScanner({
  onResult,
  paused = false,
}: {
  onResult: (value: string) => void;
  paused?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const frameRef = useRef<number | null>(null);
  const lastHit = useRef<{ value: string; at: number }>({ value: "", at: 0 });
  const pausedRef = useRef(paused);
  const onResultRef = useRef(onResult);

  const [state, setState] = useState<ScannerState>("idle");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);
  useEffect(() => {
    onResultRef.current = onResult;
  }, [onResult]);

  const stop = useCallback(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setState("idle");
  }, []);

  const tick = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || pausedRef.current) {
      frameRef.current = requestAnimationFrame(tick);
      return;
    }
    if (video.readyState === video.HAVE_ENOUGH_DATA && video.videoWidth > 0) {
      const maxWidth = 640;
      const scale = Math.min(1, maxWidth / video.videoWidth);
      canvas.width = Math.floor(video.videoWidth * scale);
      canvas.height = Math.floor(video.videoHeight * scale);
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (context) {
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const image = context.getImageData(0, 0, canvas.width, canvas.height);
        const decoded = jsQR(image.data, image.width, image.height, {
          inversionAttempts: "dontInvert",
        });
        if (decoded?.data) {
          const now = Date.now();
          if (decoded.data !== lastHit.current.value || now - lastHit.current.at > 2200) {
            lastHit.current = { value: decoded.data, at: now };
            onResultRef.current(decoded.data);
            if ("vibrate" in navigator) navigator.vibrate(60);
          }
        }
      }
    }
    frameRef.current = requestAnimationFrame(tick);
  }, []);

  const start = useCallback(async () => {
    setMessage(null);
    setState("starting");
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Este navegador no permite acceder a la cámara.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await video.play();
      }
      setState("active");
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = requestAnimationFrame(tick);
    } catch (error) {
      stop();
      setState("error");
      const name = error instanceof DOMException ? error.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        setMessage(
          "Permiso de cámara denegado. Autoriza la cámara en el navegador o introduce el código manualmente.",
        );
      } else if (name === "NotFoundError") {
        setMessage("No se ha detectado ninguna cámara en este dispositivo.");
      } else {
        setMessage(
          error instanceof Error
            ? error.message
            : "No se pudo iniciar la cámara. Use la entrada manual de código.",
        );
      }
    }
  }, [stop, tick]);

  useEffect(() => () => stop(), [stop]);

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="scan-stage">
        <video ref={videoRef} playsInline muted aria-label="Vista de la cámara para escanear" />
        {state === "active" ? (
          <>
            <div className="scan-frame" />
            <div className="scan-line" />
            <span className="scan-hint">Apunta al código QR de la etiqueta AURORA</span>
          </>
        ) : (
          <div className="empty" style={{ position: "absolute", inset: 0 }}>
            <IconCamera />
            <strong>{state === "starting" ? "Iniciando cámara…" : "Cámara desactivada"}</strong>
            <p>La imagen se procesa en el dispositivo; no se envía vídeo al servidor.</p>
          </div>
        )}
      </div>
      <canvas ref={canvasRef} style={{ display: "none" }} aria-hidden="true" />

      {message ? <div className="form-error">{message}</div> : null}

      <div className="row">
        {state === "active" ? (
          <button type="button" className="btn btn-ghost btn-block" onClick={stop}>
            Detener cámara
          </button>
        ) : (
          <button type="button" className="btn btn-primary btn-block" onClick={start} disabled={state === "starting"}>
            {state === "starting" ? <span className="spinner" /> : <IconCamera />}
            {state === "starting" ? "Solicitando permiso…" : "Activar cámara"}
          </button>
        )}
      </div>
      <p className="hint">
        Si el navegador no permite la cámara (por ejemplo, dentro de una vista embebida), utiliza la pestaña
        «Código manual»: el escáner de mano o la etiqueta incluyen el código legible.
      </p>
    </div>
  );
}
