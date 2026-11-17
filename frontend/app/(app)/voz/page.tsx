"use client";

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { VoiceReply, VoiceStatus } from "@/lib/types";
import { Badge, Card, PageHeader, useToast } from "@/components/ui";
import { IconCheck, IconInfo, IconMic, IconRefresh } from "@/components/icons";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  intent?: string;
  suggestions?: string[];
  confidence?: number;
}

interface SpeechRecognitionResultLike {
  0: { transcript: string };
  isFinal: boolean;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: { length: number; [index: number]: SpeechRecognitionResultLike };
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

const WELCOME: ChatMessage = {
  role: "assistant",
  text: "Hola, soy AURORA Voice. Puedo decirle dónde está un producto, su stock disponible, qué hay bajo mínimo, tareas, incidencias, repartos o un resumen del almacén.",
  suggestions: [
    "¿Dónde está el producto tornillo M8?",
    "¿Qué productos están bajo mínimo?",
    "¿Hay incidencias abiertas?",
    "Resumen del almacén",
  ],
};

export default function VoicePage() {
  const toast = useToast();
  const status = useApi<{ message: string; details: VoiceStatus }>("/api/v1/voice/status");
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [speakAnswers, setSpeakAnswers] = useState(false);
  const [speechSupported, setSpeechSupported] = useState({ recognition: false, synthesis: false });
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const holder = window as unknown as {
      SpeechRecognition?: SpeechRecognitionCtor;
      webkitSpeechRecognition?: SpeechRecognitionCtor;
    };
    setSpeechSupported({
      recognition: Boolean(holder.SpeechRecognition || holder.webkitSpeechRecognition),
      synthesis: "speechSynthesis" in window,
    });
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  function speak(message: string) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const synth = window.speechSynthesis;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.lang = "es-ES";
    utterance.rate = 1;
    const voices = synth.getVoices().filter((voice) => voice.lang.toLowerCase().startsWith("es"));
    const preferred = [
      "helena", "laura", "monica", "mónica", "paulina", "sabina", "elena", "google español",
    ];
    const female = voices.find((voice) =>
      preferred.some((name) => voice.name.toLowerCase().includes(name)),
    );
    if (female) utterance.voice = female;
    synth.speak(utterance);
  }

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setMessages((current) => [...current, { role: "user", text: trimmed }]);
    setText("");
    setBusy(true);
    try {
      const reply = await api<VoiceReply>("/api/v1/voice/query", {
        method: "POST",
        body: { text: trimmed, locale: "es-ES" },
      });
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: reply.answer,
          intent: reply.intent,
          suggestions: reply.suggestions,
          confidence: reply.confidence,
        },
      ]);
      if (speakAnswers) speak(reply.answer);
    } catch (err) {
      const detail = errorMessage(err);
      toast.error("No se pudo consultar", detail);
      setMessages((current) => [
        ...current,
        { role: "assistant", text: `No he podido consultar los datos: ${detail}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function startListening() {
    if (typeof window === "undefined") return;
    const holder = window as unknown as {
      SpeechRecognition?: SpeechRecognitionCtor;
      webkitSpeechRecognition?: SpeechRecognitionCtor;
    };
    const Ctor = holder.SpeechRecognition || holder.webkitSpeechRecognition;
    if (!Ctor) {
      toast.error("Micrófono no disponible", "Use Chrome, Edge o Safari actualizado, o escriba la consulta.");
      return;
    }
    const instance = new Ctor();
    instance.lang = "es-ES";
    instance.continuous = false;
    instance.interimResults = true;
    instance.onresult = (event) => {
      let finalText = "";
      let partial = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) finalText += result[0].transcript;
        else partial += result[0].transcript;
      }
      setInterim(partial);
      if (finalText.trim()) {
        setInterim("");
        void ask(finalText);
      }
    };
    instance.onerror = (event) => {
      setInterim("");
      const reason = event.error === "not-allowed" ? "Permiso de micrófono denegado." : "No se pudo reconocer la voz.";
      toast.error("Micrófono", reason);
    };
    instance.onend = () => {
      setListening(false);
      setInterim("");
    };
    recognition.current = instance;
    setListening(true);
    instance.start();
  }

  function stopListening() {
    recognition.current?.stop();
    setListening(false);
    setInterim("");
  }

  const details = status.data?.details;

  return (
    <>
      <PageHeader
        eyebrow="Asistente"
        title="AURORA Voice"
        subtitle="Hable o escriba: las respuestas salen de la base de datos real, no de un guion."
        actions={
          <button type="button" className="btn btn-ghost" onClick={status.reload}>
            <IconRefresh /> Actualizar
          </button>
        }
      />

      <div className="split" style={{ gap: 18, alignItems: "start" }}>
        <Card
          title="Conversación"
          subtitle="La transcripción se procesa en el servidor; el audio no sale del navegador"
        >
          <div className="chat" aria-live="polite">
            {messages.map((message, index) => (
              <div key={index} className={`chat-bubble ${message.role}`}>
                <div className="chat-text">{message.text}</div>
                {message.role === "assistant" && message.intent ? (
                  <div className="chat-meta">
                    <Badge tone="neutral" dot={false}>{message.intent}</Badge>
                    {typeof message.confidence === "number" ? (
                      <span className="tiny text-muted">{Math.round(message.confidence * 100)}%</span>
                    ) : null}
                    {speechSupported.synthesis ? (
                      <button type="button" className="btn btn-sm btn-ghost" onClick={() => speak(message.text)}>
                        Escuchar
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {message.suggestions?.length ? (
                  <div className="chat-suggestions">
                    {message.suggestions.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        className="chip"
                        onClick={() => ask(suggestion)}
                        disabled={busy}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
            {busy ? (
              <div className="chat-bubble assistant">
                <span className="spinner" /> Consultando datos reales…
              </div>
            ) : null}
            <div ref={endRef} />
          </div>

          <form
            className="voice-bar"
            onSubmit={(event) => {
              event.preventDefault();
              void ask(text);
            }}
          >
            <button
              type="button"
              className={`btn btn-mic${listening ? " listening" : ""}`}
              onClick={listening ? stopListening : startListening}
              aria-label={listening ? "Detener micrófono" : "Hablar"}
            >
              <IconMic />
            </button>
            <input
              className="input"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={interim || "Escriba o pulse el micrófono…"}
              maxLength={500}
              aria-label="Consulta para AURORA Voice"
            />
            <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>
              Enviar
            </button>
          </form>
          <label className="row small text-muted" style={{ marginTop: 8, gap: 8 }}>
            <input
              type="checkbox"
              checked={speakAnswers}
              onChange={(event) => {
                setSpeakAnswers(event.target.checked);
                if (!event.target.checked && "speechSynthesis" in window) window.speechSynthesis.cancel();
              }}
            />
            Leer las respuestas en voz alta
          </label>
          {!speechSupported.recognition ? (
            <div className="alert warning" style={{ marginTop: 12 }}>
              <strong>Micrófono no disponible en este navegador</strong>
              <span>Puede escribir la consulta; el reconocimiento usa Chrome, Edge o Safari actualizados.</span>
            </div>
          ) : null}
        </Card>

        <Card title="Cómo funciona" subtitle="Sin claves de terceros ni audio almacenado">
          <div className="stack" style={{ gap: 10 }}>
            <div className="row" style={{ gap: 6 }}>
              <Badge tone={details?.available ? "success" : "warning"}>
                {details?.available ? "Motor local activo" : "Motor no disponible"}
              </Badge>
              <Badge tone="info" dot={false}>es-ES</Badge>
            </div>
            <p className="small text-soft">{details?.provider_label ?? "Consultas AURORA locales"}</p>
            <ul className="check-list">
              {(details?.capabilities ?? []).map((item) => (
                <li key={item}>
                  <IconCheck /> {item}
                </li>
              ))}
            </ul>
            <div className="alert" style={{ marginTop: 4 }}>
              <IconInfo />
              <span>
                Reconocimiento y síntesis usan la Web Speech API del navegador. Solo se envía el texto
                transcrito; no se guarda el audio ni el historial en la base de datos.
              </span>
            </div>
            {status.error ? <p className="form-error">{status.error}</p> : null}
          </div>
        </Card>
      </div>
    </>
  );
}
