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
from app.services import s3 as s3_storage

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
    absolute_path: Path | None
    sha256: str
    size: int
    mime_type: str
    original_filename: str
    storage_backend: str = "local"


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
    backend = "local"
    absolute: Path | None = final_path
    if settings.storage_backend.lower() == "s3":
        try:
            s3_storage.upload_path(
                final_path, relative, content_type=mime, sha256=digest.hexdigest()
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        final_path.unlink(missing_ok=True)
        backend = "s3"
        absolute = None
    return StoredFile(
        relative_path=relative,
        absolute_path=absolute,
        sha256=digest.hexdigest(),
        size=size,
        mime_type=mime,
        original_filename=upload.filename or final_path.name,
        storage_backend=backend,
    )


def resolve_stored_path(relative_path: str) -> Path:
    """Devuelve una ruta local legible; con S3 descarga a caché de solo lectura."""
    if settings.storage_backend.lower() == "s3":
        root = Path(settings.storage_cache_dir).resolve()
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root):
            raise ValidationError("Ruta de documento no válida.", code="invalid_path")
        if candidate.exists() and candidate.is_file():
            return candidate
        return s3_storage.download_to(relative_path, candidate)

    root = Path(settings.storage_dir).resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValidationError("Ruta de documento no válida.", code="invalid_path")
    if not candidate.exists():
        raise ValidationError("El documento original no se encuentra en el almacenamiento.", code="file_missing")
    return candidate


# ---------------------------------------------------------------------------
# Delivery proof (Phase 8)
# ---------------------------------------------------------------------------
MAX_SIGNATURE_BYTES = 2 * 1024 * 1024
SIGNATURE_MIME = "image/png"


def delivery_signature_directory(delivery_reference: str) -> Path:
    safe_ref = _slug(delivery_reference, 40)
    return Path(settings.storage_dir) / "deliveries" / safe_ref


async def store_delivery_signature(upload: UploadFile, *, delivery_reference: str) -> StoredFile:
    """Store a PNG signature exactly as captured, content-addressed by SHA-256."""
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    mime = (upload.content_type or "").lower()
    if mime != SIGNATURE_MIME:
        raise ValidationError(
            "La firma debe enviarse como imagen PNG.",
            code="unsupported_signature_type",
            details={"content_type": mime or "desconocido"},
        )
    data = await upload.read(MAX_SIGNATURE_BYTES + 1)
    await upload.close()
    if not data:
        raise ValidationError("La firma está vacía.", code="empty_signature")
    if len(data) > MAX_SIGNATURE_BYTES:
        raise ValidationError("La firma supera el límite de 2 MB.", code="signature_too_large")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValidationError("El archivo no es un PNG válido.", code="invalid_signature_file")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError("El archivo no es una imagen PNG válida.", code="invalid_signature_file") from exc
    if width < 50 or height < 30:
        raise ValidationError(
            "La firma es demasiado pequeña; vuelva a capturarla.",
            code="signature_too_small",
            details={"width": width, "height": height},
        )
    if width > 4000 or height > 4000:
        raise ValidationError("La firma supera el tamaño máximo de 4000×4000 px.", code="signature_too_large")

    digest = hashlib.sha256(data).hexdigest()
    directory = delivery_signature_directory(delivery_reference)
    directory.mkdir(parents=True, exist_ok=True)
    final_path = directory / f"signature-{digest[:12]}.png"
    if not final_path.exists():
        final_path.write_bytes(data)
    relative = final_path.relative_to(Path(settings.storage_dir)).as_posix()
    backend = "local"
    absolute: Path | None = final_path
    if settings.storage_backend.lower() == "s3":
        try:
            s3_storage.upload_bytes(
                data, relative, content_type=SIGNATURE_MIME, sha256=digest
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        final_path.unlink(missing_ok=True)
        backend = "s3"
        absolute = None
    return StoredFile(
        relative_path=relative,
        absolute_path=absolute,
        sha256=digest,
        size=len(data),
        mime_type=SIGNATURE_MIME,
        original_filename=f"firma-{delivery_reference}.png",
        storage_backend=backend,
    )
