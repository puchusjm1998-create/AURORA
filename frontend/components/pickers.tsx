"use client";

import { useEffect, useRef, useState } from "react";
import { withQuery } from "@/lib/api";
import { fmtNumber, fmtQty, palletStatusMeta, trackingLabel } from "@/lib/format";
import type { Location, Page, Pallet, Product } from "@/lib/types";
import { useDebounced, useApi } from "@/lib/useApi";
import { IconPallet, IconPin, IconSearch } from "./icons";

interface PickerBaseProps {
  placeholder?: string;
  disabled?: boolean;
  autoFocus?: boolean;
}

function useCloseOnOutside<T extends HTMLElement>(onClose: () => void) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);
  return ref;
}

/* ------------------------------------------------------------------ */
/* Product picker                                                      */
/* ------------------------------------------------------------------ */
export function ProductPicker({
  value,
  onChange,
  placeholder = "Buscar producto por nombre, SKU o referencia…",
  disabled,
  autoFocus,
}: PickerBaseProps & {
  value: string | null;
  onChange: (product: Product | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(query, 250);
  const results = useApi<Page<Product>>(
    open ? withQuery("/api/v1/products", { search: debounced || null, is_active: true, limit: 10 }) : null,
    [debounced, open],
  );
  const selected = useApi<Product>(value ? `/api/v1/products/${value}` : null, [value]);
  const boxRef = useCloseOnOutside<HTMLDivElement>(() => setOpen(false));

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <div className="search-wrap">
        <IconSearch />
        <input
          className="input"
          value={open ? query : selected.data ? `${selected.data.sku} · ${selected.data.name}` : query}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          role="combobox"
          aria-expanded={open}
          aria-controls="product-picker-results"
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            if (value) onChange(null);
          }}
        />
        {value ? (
          <button
            type="button"
            style={{
              position: "absolute",
              right: 8,
              top: "50%",
              transform: "translateY(-50%)",
              background: "none",
              border: 0,
              color: "var(--muted)",
              cursor: "pointer",
              fontSize: 12,
            }}
            onClick={() => {
              onChange(null);
              setQuery("");
              setOpen(true);
            }}
            aria-label="Quitar selección"
          >
            ✕
          </button>
        ) : null}
      </div>
      {open ? (
        <div
          id="product-picker-results"
          role="listbox"
          className="card"
          style={{
            position: "absolute",
            zIndex: 50,
            top: "calc(100% + 6px)",
            left: 0,
            right: 0,
            maxHeight: 300,
            overflow: "auto",
            background: "#0d1728",
          }}
        >
          {results.loading ? <div className="empty" style={{ padding: 18 }}>Buscando…</div> : null}
          {results.data && results.data.items.length === 0 ? (
            <div className="empty" style={{ padding: 18 }}>
              Sin resultados
            </div>
          ) : null}
          {results.data?.items.map((product) => (
            <button
              key={product.id}
              type="button"
              className="nav-item"
              style={{ width: "100%", borderRadius: 0, textAlign: "left", display: "grid", gap: 2 }}
              onClick={() => {
                onChange(product);
                setOpen(false);
                setQuery("");
              }}
            >
              <span className="row" style={{ gap: 8, justifyContent: "space-between" }}>
                <span className="strong small">{product.name}</span>
                <span className="mono tiny text-accent">{product.sku}</span>
              </span>
              <span className="tiny text-muted">
                {product.category} · {trackingLabel[product.tracking_mode]} · disponible{" "}
                {fmtNumber(product.stock.available, 3)} {product.uom}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Location picker                                                     */
/* ------------------------------------------------------------------ */
export function LocationPicker({
  value,
  onChange,
  placeholder = "Buscar ubicación por código (ALM-01-P01-…)",
  disabled,
}: PickerBaseProps & {
  value: string | null;
  onChange: (location: Location | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(query, 250);
  const results = useApi<Page<Location>>(
    open
      ? withQuery("/api/v1/locations", { search: debounced || null, is_active: true, limit: 10 })
      : null,
    [debounced, open],
  );
  const selected = useApi<Location>(value ? `/api/v1/locations/${value}` : null, [value]);
  const boxRef = useCloseOnOutside<HTMLDivElement>(() => setOpen(false));

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <div className="search-wrap">
        <IconPin />
        <input
          className="input mono"
          value={open ? query : selected.data?.full_code ?? query}
          placeholder={placeholder}
          disabled={disabled}
          role="combobox"
          aria-expanded={open}
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            if (value) onChange(null);
          }}
        />
      </div>
      {open ? (
        <div
          className="card"
          role="listbox"
          style={{
            position: "absolute",
            zIndex: 50,
            top: "calc(100% + 6px)",
            left: 0,
            right: 0,
            maxHeight: 280,
            overflow: "auto",
            background: "#0d1728",
          }}
        >
          {results.loading ? <div className="empty" style={{ padding: 16 }}>Buscando…</div> : null}
          {results.data?.items.map((location) => (
            <button
              key={location.id}
              type="button"
              className="nav-item"
              style={{ width: "100%", borderRadius: 0, textAlign: "left", display: "grid", gap: 2 }}
              onClick={() => {
                onChange(location);
                setOpen(false);
                setQuery("");
              }}
            >
              <span className="row" style={{ justifyContent: "space-between" }}>
                <span className="mono small text-accent">{location.full_code}</span>
                <span className="tiny text-muted">
                  {location.occupied_pallets}/{location.capacity_pallets} palés
                </span>
              </span>
              <span className="tiny text-muted">{location.label || "Sin etiqueta"}</span>
            </button>
          ))}
          {results.data && results.data.items.length === 0 ? (
            <div className="empty" style={{ padding: 16 }}>
              Sin ubicaciones
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Pallet picker                                                       */
/* ------------------------------------------------------------------ */
export function PalletPicker({
  value,
  onChange,
  status,
  placeholder = "Buscar palé por código (AUR-PAL-…)",
  disabled,
}: PickerBaseProps & {
  value: string | null;
  onChange: (pallet: Pallet | null) => void;
  status?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(query, 250);
  const results = useApi<Page<Pallet>>(
    open
      ? withQuery("/api/v1/pallets", { search: debounced || null, status: status || null, limit: 10 })
      : null,
    [debounced, open, status],
  );
  const selected = useApi<Pallet>(value ? `/api/v1/pallets/${value}` : null, [value]);
  const boxRef = useCloseOnOutside<HTMLDivElement>(() => setOpen(false));

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <div className="search-wrap">
        <IconPallet />
        <input
          className="input mono"
          value={open ? query : selected.data?.code ?? query}
          placeholder={placeholder}
          disabled={disabled}
          role="combobox"
          aria-expanded={open}
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            if (value) onChange(null);
          }}
        />
      </div>
      {open ? (
        <div
          className="card"
          role="listbox"
          style={{
            position: "absolute",
            zIndex: 50,
            top: "calc(100% + 6px)",
            left: 0,
            right: 0,
            maxHeight: 280,
            overflow: "auto",
            background: "#0d1728",
          }}
        >
          {results.data?.items.map((pallet) => {
            const meta = palletStatusMeta[pallet.status];
            return (
              <button
                key={pallet.id}
                type="button"
                className="nav-item"
                style={{ width: "100%", borderRadius: 0, textAlign: "left", display: "grid", gap: 2 }}
                onClick={() => {
                  onChange(pallet);
                  setOpen(false);
                  setQuery("");
                }}
              >
                <span className="row" style={{ justifyContent: "space-between" }}>
                  <span className="mono small text-accent">{pallet.code}</span>
                  <span className={`badge ${meta.tone}`} style={{ fontSize: 9 }}>
                    {meta.label}
                  </span>
                </span>
                <span className="tiny text-muted">
                  {pallet.location_code ?? "sin ubicación"} · {fmtQty(pallet.total_units)} uds ·{" "}
                  {pallet.item_count} refs
                </span>
              </button>
            );
          })}
          {results.data && results.data.items.length === 0 ? (
            <div className="empty" style={{ padding: 16 }}>
              Sin palés
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
