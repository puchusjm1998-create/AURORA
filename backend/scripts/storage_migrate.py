"""Migra los documentos locales a un bucket S3 compatible.

El proceso es idempotente: compara tamaño y SHA-256 con los metadatos del
objeto y omite los ficheros ya migrados. No borra el original local; cuando la
verificación termina, puede conservarlo como copia de seguridad o retirarlo
manualmente. No toca la base de datos: las claves relativas no cambian.

    cd backend
    export STORAGE_BACKEND=s3 S3_BUCKET=... S3_ENDPOINT_URL=...
    ../.venv/bin/python -m scripts.storage_migrate --dry-run
    ../.venv/bin/python -m scripts.storage_migrate
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services import s3 as s3_storage

settings = get_settings()

MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_type(path: Path) -> str:
    return MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")


def migrate(
    source: Path | None = None, *, dry_run: bool = False, verify: bool = True
) -> dict[str, Any]:
    source = Path(source or settings.storage_dir)
    if not settings.s3_configured:
        raise RuntimeError(
            "Configure STORAGE_BACKEND=s3 y S3_BUCKET antes de migrar documentos."
        )
    if not source.exists():
        return {"source": str(source), "files": 0, "uploaded": 0, "skipped": 0,
                "bytes": 0, "dry_run": dry_run, "errors": []}
    stats: dict[str, Any] = {
        "source": str(source),
        "files": 0,
        "uploaded": 0,
        "skipped": 0,
        "bytes": 0,
        "dry_run": dry_run,
        "errors": [],
    }
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or path.name.endswith(".part"):
            continue
        stats["files"] += 1
        relative = path.relative_to(source).as_posix()
        digest = sha256_file(path)
        size = path.stat().st_size
        existing = s3_storage.head(relative)
        if existing and existing.get("size") == size and existing.get("sha256") == digest:
            stats["skipped"] += 1
            continue
        if dry_run:
            stats["uploaded"] += 1
            stats["bytes"] += size
            print(f"[dry-run] {relative} ({size} bytes)")
            continue
        try:
            s3_storage.upload_path(
                path, relative, content_type=_content_type(path), sha256=digest
            )
            if verify:
                downloaded = s3_storage.download_bytes(relative)
                remote = hashlib.sha256(downloaded).hexdigest()
                if remote != digest:
                    raise ValueError(
                        f"verificación fallida: {remote} != {digest}"
                    )
            stats["uploaded"] += 1
            stats["bytes"] += size
            print(f"OK {relative} ({size} bytes)")
        except Exception as exc:  # noqa: BLE001 - se resume al final
            stats["errors"].append({"path": relative, "error": str(exc)[:300]})
            print(f"ERROR {relative}: {exc}", file=sys.stderr)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="directorio local de documentos")
    parser.add_argument("--dry-run", action="store_true", help="solo listar")
    parser.add_argument(
        "--no-verify", action="store_true", help="no descargar para comparar SHA-256"
    )
    args = parser.parse_args()
    stats = migrate(
        Path(args.source) if args.source else None,
        dry_run=args.dry_run,
        verify=not args.no_verify,
    )
    print(
        f"Ficheros: {stats['files']} · subidos: {stats['uploaded']} · "
        f"omitidos: {stats['skipped']} · bytes: {stats['bytes']} · "
        f"errores: {len(stats['errors'])}"
    )
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
