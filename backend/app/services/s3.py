"""Adaptador S3 compatible para documentos y firmas.

No cambia la clave lógica que se guarda en la base de datos (``file_path`` /
``signature_path``): si ``STORAGE_BACKEND=s3``, esa misma ruta relativa se
convierte en una clave dentro del bucket. Se admite AWS S3,MinIO, Ceph y
cualquier endpoint compatible con la API S3 v4.
"""

from __future__ import annotations

from pathlib import Path

from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.errors import AppError

_MISSING_CODES = {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}


def _client():
    settings = get_settings()
    if not settings.s3_configured:
        raise AppError(
            "El almacenamiento S3 no está configurado (S3_BUCKET).",
            status_code=503,
            code="s3_not_configured",
        )
    import boto3

    kwargs: dict[str, object] = {
        "service_name": "s3",
        "region_name": settings.s3_region,
        "config": BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": settings.s3_addressing_style},
            connect_timeout=settings.s3_timeout,
            read_timeout=settings.s3_timeout,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    }
    if settings.s3_endpoint_url.strip():
        kwargs["endpoint_url"] = settings.s3_endpoint_url.strip()
    if settings.s3_access_key_id.strip():
        kwargs["aws_access_key_id"] = settings.s3_access_key_id.strip()
        kwargs["aws_secret_access_key"] = settings.s3_secret_access_key.strip()
    return boto3.client(**kwargs)


def object_key(relative_path: str) -> str:
    settings = get_settings()
    prefix = settings.s3_prefix.strip().strip("/")
    clean = relative_path.replace("\\", "/").lstrip("/")
    return f"{prefix}/{clean}" if prefix else clean


def upload_path(
    source: Path, relative_path: str, *, content_type: str, sha256: str = ""
) -> None:
    settings = get_settings()
    try:
        _client().upload_file(
            str(source),
            settings.s3_bucket,
            object_key(relative_path),
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {"sha256": sha256} if sha256 else {},
            },
        )
    except (BotoCoreError, ClientError) as exc:
        raise AppError(
            "No se pudo guardar el documento en S3.",
            status_code=503,
            code="storage_unavailable",
            details={"error": str(exc)[:300]},
        ) from exc


def upload_bytes(
    data: bytes, relative_path: str, *, content_type: str, sha256: str = ""
) -> None:
    settings = get_settings()
    try:
        _client().put_object(
            Bucket=settings.s3_bucket,
            Key=object_key(relative_path),
            Body=data,
            ContentType=content_type,
            Metadata={"sha256": sha256} if sha256 else {},
        )
    except (BotoCoreError, ClientError) as exc:
        raise AppError(
            "No se pudo guardar el archivo en S3.",
            status_code=503,
            code="storage_unavailable",
            details={"error": str(exc)[:300]},
        ) from exc


def download_to(relative_path: str, destination: Path) -> Path:
    settings = get_settings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.part")
    try:
        _client().download_file(
            settings.s3_bucket, object_key(relative_path), str(temp)
        )
        temp.replace(destination)
    except (BotoCoreError, ClientError) as exc:
        temp.unlink(missing_ok=True)
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code in _MISSING_CODES:
            raise AppError(
                "El documento original no se encuentra en el almacenamiento S3.",
                status_code=404,
                code="file_missing",
            ) from exc
        raise AppError(
            "No se pudo descargar el documento desde S3.",
            status_code=503,
            code="storage_unavailable",
            details={"error": str(exc)[:300]},
        ) from exc
    return destination


def delete(relative_path: str) -> None:
    settings = get_settings()
    try:
        _client().delete_object(Bucket=settings.s3_bucket, Key=object_key(relative_path))
    except (BotoCoreError, ClientError):
        # El borrado es best-effort: nunca debe romper una operación de negocio.
        return


def status() -> dict[str, object]:
    settings = get_settings()
    requested = settings.storage_backend.strip().lower() == "s3"
    result: dict[str, object] = {
        "backend": "s3" if requested else "local",
        "bucket": settings.s3_bucket or None,
        "prefix": settings.s3_prefix,
        "endpoint": settings.s3_endpoint_url or "AWS",
        "reachable": not requested,
    }
    if not requested:
        return result
    if not settings.s3_configured:
        result["error"] = "Falta S3_BUCKET; el backend S3 no está configurado."
        return result
    try:
        _client().list_objects_v2(Bucket=settings.s3_bucket, MaxKeys=1)
        result["reachable"] = True
    except (BotoCoreError, ClientError) as exc:
        result["error"] = str(exc)[:300]
    return result
