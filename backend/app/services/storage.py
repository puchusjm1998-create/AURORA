"""Document storage.

Original invoices are stored untouched in a hierarchical structure:

    storage/invoices/<AÑO>/<MES>/<DÍA>/<PROVEEDOR>/<FACTURA>/<sha256-prefix>-<nombre>

The original file is never modified; any OCR/extraction output is stored in the
database, not in the file. Files are also content-addressed (sha256) so
duplicates can be detected and corruption verified.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import ValidationError

settings = get_settings()

ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
}


@dataclass
class StoredFile:
    relative_path: str
    absolute_path: Path
    sha256: str
    size: int
    mime_type: str
    original_filename: str


def _slug(value: str, max_length: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-").upper()
    return normalized[:max_length] or "SIN-DATO"


def invoice_directory(invoice_date: date, supplier: str, number: str) -> Path:
    return (
        Path(settings.storage_dir)
        / "invoices"
        / f"{invoice_date.year:04d}"
        / f"{invoice_date.month:02d}"
        / f"{invoice_date.day:02d}"
        / _slug(supplier)
        / _slug(number)
    )


async def store_invoice_file(
    upload: UploadFile,
    *,
    invoice_date: date,
    supplier: str,
    number: str,
) -> StoredFile:
    mime = (upload.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        raise ValidationError(
            "Formato no admitido. Suba un PDF, JPG, PNG, WEBP o TIFF.",
            code="unsupported_file_type",
            details={"content_type": mime or "desconocido"},
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    directory = invoice_directory(invoice_date, supplier, number)
    directory.mkdir(parents=True, exist_ok=True)

    safe_name = _slug(Path(upload.filename or "factura").stem, 80) + ALLOWED_MIME[mime]
    temp_path = directory / f".upload-{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with temp_path.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationError(
                        f"El archivo supera el límite de {settings.max_upload_mb} MB.",
                        code="file_too_large",
                    )
                digest.update(chunk)
                handle.write(chunk)
        if size == 0:
            raise ValidationError("El archivo está vacío.", code="empty_file")
        final_name = f"{digest.hexdigest()[:12]}-{safe_name}"
        final_path = directory / final_name
        if final_path.exists():
            temp_path.unlink(missing_ok=True)
        else:
            shutil.move(str(temp_path), str(final_path))
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    relative = final_path.relative_to(Path(settings.storage_dir)).as_posix()
    return StoredFile(
        relative_path=relative,
        absolute_path=final_path,
        sha256=digest.hexdigest(),
        size=size,
        mime_type=mime,
        original_filename=upload.filename or final_path.name,
    )


def resolve_stored_path(relative_path: str) -> Path:
    root = Path(settings.storage_dir).resolve()
    candidate = (root / relative_path).resolve()
    if not str(candidate).startswith(str(root)):
        raise ValidationError("Ruta de documento no válida.", code="invalid_path")
    if not candidate.exists():
        raise ValidationError("El documento original no se encuentra en el almacenamiento.", code="file_missing")
    return candidate
