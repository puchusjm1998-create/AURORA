"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, errorMessage, qrUrl } from "@/lib/api";
import type { LabelData, Product } from "@/lib/types";
import { LocationPicker, PalletPicker, ProductPicker } from "@/components/pickers";
import {
  Badge,
  ErrorBlock,
  Field,
  LoadingBlock,
  PageHeader,
  useToast,
} from "@/components/ui";
import { IconPrint, IconQr } from "@/components/icons";

type LabelKind = "product" | "pallet" | "location" | "unit" | "employee";

const KIND_LABEL: Record<LabelKind, string> = {
  product: "Producto",
  pallet: "Palé",
  location: "Ubicación",
  unit: "Objeto individual",
  employee: "Trabajador",
};

function LabelBuilder() {
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const kind = (params.get("kind") ?? "product") as LabelKind;
  const idsParam = params.get("ids") ?? "";
  const ids = useMemo(
    () => idsParam.split(",").map((value) => value.trim()).filter(Boolean),
    [idsParam],
  );

  const [labels, setLabels] = useState<LabelData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copies, setCopies] = useState(1);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

  useEffect(() => {
    if (!ids.length) {
      setLabels([]);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all(ids.map((id) => api<LabelData>(`/api/v1/qr/labels/${kind}/${encodeURIComponent(id)}`)))
      .then((result) => {
        if (active) setLabels(result);
      })
      .catch((err) => {
        if (active) setError(errorMessage(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [kind, ids]);

  const repeated = useMemo(
    () => labels.flatMap((label) => Array.from({ length: Math.max(1, copies) }, () => label)),
    [labels, copies],
  );

  function go(nextIds: string[]) {
    router.replace(`/etiquetas?kind=${kind}&ids=${nextIds.join(",")}`);
  }

  return (
    <div className="print-page">
      <div className="print-bar no-print">
        <Link href={kind === "pallet" ? "/pales" : kind === "location" ? "/almacenes" : "/inventario"} className="btn btn-ghost">
          Volver
        </Link>
        <span className="mono small text-muted">
          {labels.length} etiqueta{labels.length === 1 ? "" : "s"} · {KIND_LABEL[kind]}
        </span>
        <span className="spacer" />
        <label className="row" style={{ gap: 6 }}>
          <span className="small">Copias</span>
          <input
            className="input"
            type="number"
            min={1}
            max={20}
            value={copies}
            onChange={(event) => setCopies(Math.max(1, Math.min(20, Number(event.target.value) || 1)))}
            style={{ width: 72 }}
          />
        </label>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => {
            if (!labels.length) {
              toast.error("No hay etiquetas para imprimir");
              return;
            }
            window.print();
          }}
          disabled={!labels.length}
        >
          <IconPrint /> Imprimir
        </button>
      </div>

      <div className="no-print" style={{ padding: "20px 18px 0" }}>
        <div className="card" style={{ background: "#0b1322" }}>
          <div className="card-body">
            <div className="row" style={{ gap: 12, alignItems: "flex-end" }}>
              <Field label="Tipo de etiqueta">
                <select
                  className="select"
                  value={kind}
                  onChange={(event) => router.replace(`/etiquetas?kind=${event.target.value}`)}
                >
                  {Object.entries(KIND_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <div style={{ flex: 1, minWidth: 260 }}>
                <Field label="Añadir elemento" hint="Busca y selecciona; se añadirá a la hoja de etiquetas.">
                  {kind === "product" ? (
                    <ProductPicker
                      value={selectedProduct?.id ?? null}
                      onChange={(product) => {
                        setSelectedProduct(product);
                        if (product) go([...ids, product.id]);
                      }}
                    />
                  ) : kind === "pallet" ? (
                    <PalletPicker
                      value={null}
                      onChange={(pallet) => pallet && go([...ids, pallet.id])}
                    />
                  ) : kind === "location" ? (
                    <LocationPicker
                      value={null}
                      onChange={(location) => location && go([...ids, location.id])}
                    />
                  ) : (
                    <p className="hint" style={{ paddingTop: 8 }}>
                      Las etiquetas de {KIND_LABEL[kind].toLowerCase()} se generan desde su ficha
                      correspondiente (producto, palé, personal).
                    </p>
                  )}
                </Field>
              </div>
              <div className="row" style={{ paddingBottom: 2 }}>
                <button type="button" className="btn btn-ghost" onClick={() => go([])} disabled={!ids.length}>
                  Vaciar
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div style={{ padding: "18px" }}>
        {error ? <ErrorBlock message={error} /> : null}
        {loading ? <LoadingBlock label="Generando etiquetas…" /> : null}
        {!loading && !labels.length && !error ? (
          <div className="card">
            <div className="empty">
              <IconQr />
              <strong>Sin etiquetas seleccionadas</strong>
              <p>
                Añade elementos con el buscador o genera etiquetas desde las fichas de producto, palé,
                ubicación o personal.
              </p>
            </div>
          </div>
        ) : null}
      </div>

      {repeated.length ? (
        <div className="label-sheet">
          {repeated.map((label, index) => (
            <article className="label" key={`${label.code}-${index}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={qrUrl(label.payload, 5)} alt={`QR ${label.code}`} width={98} height={98} />
              <div>
                <div className="lb-kind">{KIND_LABEL[label.kind as LabelKind] ?? label.kind}</div>
                <div className="lb-title">{label.title}</div>
                <div className="lb-code">{label.code}</div>
                {label.lines.map((line, lineIndex) => (
                  <div className="lb-line" key={lineIndex}>
                    {line}
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      ) : null}

      <div className="no-print" style={{ padding: 18 }}>
        <div className="alert">
          <strong>Formato de impresión</strong>
          <span>
            Etiquetas de 68 × 42 mm, varias por hoja A4. El QR codifica{" "}
            <code className="inline-code">aurora://tipo/código</code> y el código legible permite introducirlo
            manualmente si la cámara no está disponible.
          </span>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <Badge tone="accent" dot={false}>Consejo: imprime en adhesivo A4 y recorta</Badge>
        </div>
      </div>
    </div>
  );
}

export default function LabelsPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <LabelBuilder />
    </Suspense>
  );
}
