"use client";

/** Utilidades del lector NFC del navegador (Web NFC). */

export function webNfcSupported(): boolean {
  return typeof window !== "undefined" && "NDEFReader" in window;
}

function decodeRecord(record: NDEFRecord): string {
  if (!record.data) return "";
  try {
    const bytes =
      record.data instanceof ArrayBuffer
        ? new Uint8Array(record.data)
        : new Uint8Array(
            record.data.buffer,
            record.data.byteOffset,
            record.data.byteLength,
          );
    return new TextDecoder(record.encoding || "utf-8").decode(bytes);
  } catch {
    return "";
  }
}

/** Extrae el token AURORA de un mensaje NDEF de texto o URL. */
export function tokenFromMessage(message: NDEFMessage): string | null {
  for (const record of message.records) {
    const text = decodeRecord(record).trim();
    if (!text) continue;
    const direct = text.match(/AUR-NFC-[A-Za-z0-9_-]{8,}/);
    if (direct) return direct[0];
    if (record.recordType === "url" || /^https?:\/\//i.test(text)) {
      try {
        const url = new URL(text, window.location.origin);
        const queryToken = url.searchParams.get("token");
        if (queryToken?.startsWith("AUR-NFC-")) return queryToken;
        const last = url.pathname.split("/").filter(Boolean).pop();
        if (last?.startsWith("AUR-NFC-")) return last;
      } catch {
        // No es una URL válida; se ignora el registro.
      }
    }
  }
  return null;
}

/** Graba el token en una etiqueta NDEF. Requiere permiso y una etiqueta cerca. */
export async function writeNfcToken(token: string): Promise<void> {
  if (!webNfcSupported()) {
    throw new Error("Web NFC no está disponible en este navegador.");
  }
  const writer = new NDEFReader();
  await writer.write({
    records: [
      {
        recordType: "text",
        lang: "es",
        encoding: "utf-8",
        data: token,
      },
    ],
  });
}
