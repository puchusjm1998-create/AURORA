export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type QueryValue = string | number | boolean | null | undefined;

export function withQuery(path: string, params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  query?: Record<string, QueryValue>;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, query, headers, ...rest } = options;
  const url = API_BASE + withQuery(path, query);
  const isForm = body instanceof FormData;
  const finalHeaders = new Headers(headers);
  if (!isForm && body !== undefined) finalHeaders.set("Content-Type", "application/json");
  finalHeaders.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: finalHeaders,
      credentials: "include",
      body: isForm ? (body as FormData) : body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "No se pudo conectar con el servidor. Compruebe la conexión.");
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") ?? "";
  if (!response.ok) {
    let code = "http_error";
    let message = `Error ${response.status}`;
    let details: unknown = undefined;
    if (contentType.includes("application/json")) {
      try {
        const payload = await response.json();
        const error = payload?.error ?? payload?.detail;
        if (typeof error === "string") {
          message = error;
        } else if (error) {
          code = error.code ?? code;
          message = error.message ?? message;
          details = error.details;
        }
      } catch {
        /* keep the default message */
      }
    }
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("aurora:unauthorized"));
    }
    throw new ApiError(response.status, code, message, details);
  }

  if (contentType.includes("application/json")) return (await response.json()) as T;
  return (await response.text()) as unknown as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.details && typeof error.details === "object" && "fields" in error.details) {
      const fields = (error.details as { fields?: { field: string; message: string }[] }).fields;
      if (fields?.length) {
        return `${error.message} (${fields.map((f) => `${f.field}: ${f.message}`).join("; ")})`;
      }
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Se ha producido un error inesperado.";
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(API_BASE + path, { credentials: "include" });
  if (!response.ok) throw new ApiError(response.status, "download_failed", "No se pudo generar el archivo.");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function qrUrl(payload: string, boxSize = 8): string {
  return API_BASE + withQuery("/api/v1/qr", { payload, box_size: boxSize });
}
