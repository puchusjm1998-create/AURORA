"""Extracción real de datos de facturas: PDF con capa de texto y OCR local.

No se envía ningún documento a terceros. Los PDF con texto se leen directamente;
los PDF escaneados y las imágenes se rasterizan y se procesan con RapidOCR
(modelos ONNX incluidos en el paquete). El resultado es siempre una *propuesta*:
la persona revisa y confirma antes de crear líneas.
"""

from __future__ import annotations

import logging
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("aurora.ocr")

MAX_PAGES = 5
MAX_TEXT_CHARS = 200_000
ENGINE_NAME = "RapidOCR ONNX (local)"

_engine: Any | None = None
_engine_error: str | None = None


@dataclass
class ExtractionResult:
    status: str
    engine: str
    method: str
    confidence: float
    raw_text: str
    parsed: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0


def engine_status() -> dict[str, Any]:
    """Comprueba si el motor local está disponible sin cargarlo en memoria."""
    global _engine_error
    try:
        import rapidocr_onnxruntime  # noqa: F401

        available = True
        error = None
    except Exception as exc:  # noqa: BLE001 - dependencia opcional
        available = False
        error = str(exc)
        _engine_error = error
    return {
        "configured": True,
        "available": available,
        "engine": ENGINE_NAME,
        "provider": "local",
        "external_service": False,
        "max_pages": MAX_PAGES,
        "supported": ["application/pdf", "image/jpeg", "image/png", "image/webp", "image/tiff"],
        "error": error,
        "human_review_required": True,
    }


def _get_engine() -> Any:
    global _engine, _engine_error
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        try:
            _engine = RapidOCR()
            _engine_error = None
        except Exception as exc:  # noqa: BLE001
            _engine_error = str(exc)
            raise
    return _engine


def reset_engine_for_tests() -> None:
    global _engine, _engine_error
    _engine = None
    _engine_error = None


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\xa0", " ").replace("\r", "\n")
    return "\n".join(" ".join(line.split()) for line in text.splitlines()).strip()


def _ocr_image(path: Path) -> tuple[str, float]:
    engine = _get_engine()
    result, _ = engine(str(path))
    if not result:
        return "", 0.0
    items = []
    for box, text, score in result:
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        items.append(
            {
                "x": min(xs),
                "x2": max(xs),
                "y": (min(ys) + max(ys)) / 2,
                "h": max(ys) - min(ys),
                "text": str(text).strip(),
                "score": float(score),
            }
        )
    items.sort(key=lambda item: (item["y"], item["x"]))
    rows: list[list[dict[str, Any]]] = []
    for item in items:
        placed = False
        for row in rows:
            row_height = max(row[0]["h"], item["h"], 8)
            if abs(row[0]["y"] - item["y"]) <= row_height * 0.65:
                row.append(item)
                placed = True
                break
        if not placed:
            rows.append([item])
    rows.sort(key=lambda row: min(item["y"] for item in row))

    lines: list[str] = []
    scores: list[float] = []
    for row in rows:
        row.sort(key=lambda item: item["x"])
        parts: list[str] = []
        previous: dict[str, Any] | None = None
        for item in row:
            if previous is not None:
                gap = item["x"] - previous["x2"]
                char_width = max(previous["h"] * 0.45, 4)
                parts.append("\t" if gap > char_width * 2.2 else " ")
            parts.append(item["text"])
            scores.append(item["score"])
            previous = item
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    confidence = sum(scores) / len(scores) if scores else 0.0
    return "\n".join(lines), confidence


def _pdf_text(path: Path) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = reader.pages[:MAX_PAGES]
    chunks = []
    for page in pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - una página corrupta no invalida el resto
            logger.warning("No se pudo leer texto de una página: %s", exc)
    return "\n".join(chunks), len(pages)


def _pdf_ocr(path: Path) -> tuple[str, float, int]:
    import pymupdf

    document = pymupdf.open(str(path))
    page_count = min(len(document), MAX_PAGES)
    chunks: list[str] = []
    scores: list[float] = []
    with tempfile.TemporaryDirectory(prefix="aurora-ocr-") as temporary:
        for index in range(page_count):
            page = document[index]
            pixmap = page.get_pixmap(dpi=180, colorspace=pymupdf.csRGB)
            image_path = Path(temporary) / f"pagina-{index + 1}.png"
            pixmap.save(str(image_path))
            text, confidence = _ocr_image(image_path)
            chunks.append(text)
            if confidence:
                scores.append(confidence)
    document.close()
    return "\n".join(chunks), (sum(scores) / len(scores) if scores else 0.0), page_count


def extract_document(path: Path, mime_type: str) -> ExtractionResult:
    """Devuelve texto y campos propuestos; nunca inventa una factura completa."""
    mime = (mime_type or "").lower()
    page_count = 0
    ocr_confidence = 0.0
    if mime == "application/pdf":
        text, page_count = _pdf_text(path)
        cleaned = _clean(text)
        if len(cleaned) >= 80 and re.search(r"factura|total|iva|proveedor", cleaned, re.I):
            method = "pdf_text"
            confidence = 0.99
        else:
            text, ocr_confidence, page_count = _pdf_ocr(path)
            method = "pdf_ocr"
            confidence = ocr_confidence
    elif mime.startswith("image/"):
        text, confidence = _ocr_image(path)
        method = "image_ocr"
        page_count = 1
    else:
        raise ValueError("Formato no admitido para OCR")

    cleaned = _clean(text)[:MAX_TEXT_CHARS]
    if not cleaned:
        return ExtractionResult(
            status="failed",
            engine=ENGINE_NAME,
            method=method,
            confidence=0.0,
            raw_text="",
            parsed={},
            warnings=["No se ha podido leer texto del documento."],
            page_count=page_count,
        )

    parsed, warnings = parse_invoice_text(cleaned)
    return ExtractionResult(
        status="done",
        engine=ENGINE_NAME,
        method=method,
        confidence=round(confidence, 4),
        raw_text=cleaned,
        parsed=parsed,
        warnings=warnings,
        page_count=page_count,
    )


# ---------------------------------------------------------------------------
# Parser de facturas españolas
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)*")
_DATE_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")


def _decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    candidate = value.strip().replace("€", "").replace("EUR", "").strip()
    candidate = re.sub(r"[^\d.,-]", "", candidate)
    if not candidate:
        return None
    if "," in candidate:
        candidate = candidate.replace(".", "").replace(",", ".")
    elif candidate.count(".") > 1:
        candidate = candidate.replace(".", "")
    try:
        return Decimal(candidate)
    except InvalidOperation:
        return None


def _last_number(line: str) -> Decimal | None:
    values = _NUMBER_RE.findall(line)
    return _decimal(values[-1]) if values else None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    match = _DATE_RE.search(raw)
    if not match:
        return None
    day, month, year = match.groups()
    year_number = int(year)
    if year_number < 100:
        year_number += 2000
    try:
        return date(year_number, int(month), int(day))
    except ValueError:
        return None


def _parse_line(line: str) -> dict[str, Any] | None:
    low = line.lower()
    if re.search(r"base imponible|subtotal|\biva\b|total|descuento|portes|forma de pago", low):
        return None
    cells = [cell.strip() for cell in re.split(r"\t|\s{2,}", line) if cell.strip()]
    quantity = price = total = None
    description = ""
    if len(cells) >= 4:
        quantity = _decimal(cells[-3])
        price = _decimal(cells[-2])
        total = _decimal(cells[-1])
        description = " ".join(cells[:-3])
    if not (quantity and price is not None and total is not None):
        match = re.match(
            r"^(?P<desc>.+?[A-Za-zÁÉÍÓÚÜÑáéíóúüñ].*?)\s+"
            r"(?P<qty>\d+(?:[.,]\d+)?)\s+"
            r"(?P<price>\d+[.,]\d{2,4})\s+"
            r"(?P<total>\d+[.,]\d{2})\s*(?:EUR|€)?$",
            line,
            re.I,
        )
        if not match:
            return None
        description = match.group("desc")
        quantity = _decimal(match.group("qty"))
        price = _decimal(match.group("price"))
        total = _decimal(match.group("total"))
    description = re.sub(r"\s+", " ", description).strip(" .-\t")
    if len(description) < 3 or quantity is None or quantity <= 0 or price is None or price < 0:
        return None
    if len(description) > 400:
        description = description[:400]
    return {
        "description": description,
        "quantity": quantity,
        "unit_price": price,
        "line_total": total,
    }


def parse_invoice_text(text: str) -> tuple[dict[str, Any], list[str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    warnings: list[str] = []
    combined = "\n".join(lines)

    supplier_name = None
    tax_id_match = re.search(
        r"\b(?:CIF|NIF|VAT|C\.?I\.?F\.?)\s*[:]?\s*([A-Z]\s?-?\s?\d{7}\s?-?\s?[0-9A-J]|\d{8}\s?-?\s?[A-Z])\b",
        combined,
        re.I,
    )
    supplier_tax_id = re.sub(r"\s+", "", tax_id_match.group(1)).upper() if tax_id_match else None
    for line in lines[:10]:
        candidate = re.split(r"\b(?:CIF|NIF|VAT)\b", line, flags=re.I)[0].strip(" .:-")
        if not candidate or len(candidate) < 3:
            continue
        if re.search(r"factura|fecha|n[ºo°]|tel[eé]fono|direcci[oó]n|c\/", candidate, re.I):
            continue
        if re.search(r"\b(S\.?L\.?|S\.?A\.?|S\.?L\.?U\.?|C\.?B\.?|S\.?COOP)\b", candidate, re.I) or supplier_tax_id:
            supplier_name = re.sub(r"\s+", " ", candidate)
            break
    if supplier_name is None and lines:
        first = lines[0].strip(" .:-")
        if 3 <= len(first) <= 120 and not re.search(r"factura|fecha|total", first, re.I):
            supplier_name = first

    number = None
    number_patterns = [
        r"(?:n[ºo°]\.?|n[uú]mero|numero)\s*[:#]\s*([A-Z0-9][A-Z0-9./_-]{2,})",
        r"factura\s*(?:n[ºo°]\.?|n[uú]mero|numero)?\s*[:#]\s*([A-Z0-9][A-Z0-9./_-]{2,})",
        r"factura\s+([A-Z]?\d[A-Z0-9./_-]{2,})",
    ]
    for pattern in number_patterns:
        number_match = re.search(pattern, combined, re.I)
        if not number_match:
            continue
        candidate = number_match.group(1).strip(" .:-")
        if not re.search(r"\d", candidate):
            continue
        if _DATE_RE.fullmatch(candidate) or re.fullmatch(r"\d{4}", candidate):
            continue
        number = candidate
        break

    invoice_date = None
    for line in lines:
        if re.search(r"fecha", line, re.I) and not re.search(r"vencimiento", line, re.I):
            invoice_date = _parse_date(line)
            if invoice_date:
                break
    if invoice_date is None:
        all_dates = []
        for match in _DATE_RE.finditer(combined):
            parsed = _parse_date(match.group(0))
            if parsed:
                all_dates.append(parsed)
        invoice_date = all_dates[0] if all_dates else None

    due_date = None
    for line in lines:
        if re.search(r"vencimiento|fecha de pago", line, re.I):
            due_date = _parse_date(line)
            if due_date:
                break

    subtotal = tax_total = total = None
    tax_rate = Decimal("21")
    for line in lines:
        low = line.lower()
        if re.search(r"base imponible|subtotal|base\s*:", low):
            subtotal = _last_number(line) or subtotal
        if re.search(r"\biva\b", low):
            rate = re.search(r"(\d{1,2})\s*%", line)
            if rate:
                tax_rate = Decimal(rate.group(1))
            if not re.search(r"^\s*total", low):
                tax_total = _last_number(line) or tax_total
        if re.search(r"total\s+factura|total\s*:|^\s*total\b", low):
            total = _last_number(line) or total

    if total is None:
        warnings.append("No se ha identificado el total de la factura.")
    if subtotal is not None and total is not None and subtotal > total:
        warnings.append("La base imponible es mayor que el total; revise la lectura.")

    items: list[dict[str, Any]] = []
    for line in lines:
        parsed_line = _parse_line(line)
        if parsed_line:
            parsed_line["tax_rate"] = tax_rate
            items.append(parsed_line)
    if not items:
        warnings.append("No se han identificado líneas de detalle; revíselas manualmente.")
    if items and subtotal is not None:
        computed = sum(
            (item["quantity"] * item["unit_price"]).quantize(Decimal("0.01")) for item in items
        )
        if abs(computed - subtotal) > Decimal("0.05"):
            warnings.append(
                f"La suma de líneas ({computed} €) no coincide con la base ({subtotal} €)."
            )
    if supplier_name is None:
        warnings.append("No se ha identificado el proveedor.")
    if number is None:
        warnings.append("No se ha identificado el número de factura.")
    if invoice_date is None:
        warnings.append("No se ha identificado la fecha de factura.")

    parsed = {
        "supplier_name": supplier_name,
        "supplier_tax_id": supplier_tax_id,
        "invoice_number": number,
        "invoice_date": invoice_date.isoformat() if invoice_date else None,
        "due_date": due_date.isoformat() if due_date else None,
        "currency": "EUR",
        "subtotal": str(subtotal) if subtotal is not None else None,
        "tax_total": str(tax_total) if tax_total is not None else None,
        "total": str(total) if total is not None else None,
        "tax_rate": str(tax_rate),
        "lines": items,
    }
    return parsed, warnings


def confidence_score(parsed: dict[str, Any], ocr_confidence: float, method: str) -> float:
    """Confianza declarada: cobertura de campos, no una probabilidad inventada."""
    checks = [
        bool(parsed.get("supplier_name")),
        bool(parsed.get("invoice_number")),
        bool(parsed.get("invoice_date")),
        bool(parsed.get("total")),
        bool(parsed.get("lines")),
    ]
    coverage = sum(checks) / len(checks)
    if method == "pdf_text":
        return round(0.55 + coverage * 0.45, 4)
    return round(coverage * 0.65 + min(max(ocr_confidence, 0.0), 1.0) * 0.35, 4)
