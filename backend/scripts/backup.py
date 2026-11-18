"""Copias de seguridad verificables de AURORA LOGISTICS AI.

Empaqueta en un directorio fechado la base de datos, el volumen de documentos
originales y un manifiesto con tamaños y huellas SHA-256 para poder comprobar
que la copia es íntegra y restaurable.

Uso habitual (con el servicio parado o en una ventana de baja actividad):

    cd backend
    ../.venv/bin/python -m scripts.backup                      # copia completa
    ../.venv/bin/python -m scripts.backup --keep 14            # retención
    ../.venv/bin/python -m scripts.backup --list               # ver copias
    ../.venv/bin/python -m scripts.backup --restore backups/aurora-... --force

SQLite se copia con la API de backup del motor (consistente con la base viva).
PostgreSQL se vuelca con ``pg_dump -Fc``; la restauración usa ``pg_restore``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR, get_settings

settings = get_settings()

BACKUP_PREFIX = "aurora-"
MANIFEST = "manifest.json"


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def utc_stamp(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def slug(text: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.strip())
    return cleaned.strip("-")[:40] or "manual"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_path(database_url: str) -> Path | None:
    """Devuelve la ruta del fichero SQLite o ``None`` si el motor es PostgreSQL."""
    if not database_url.startswith("sqlite"):
        return None
    raw = database_url.split("///", 1)[-1]
    path = Path(raw)
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return path


def build_name(label: str | None = None, moment: datetime | None = None) -> str:
    stamp = utc_stamp(moment)
    return f"{BACKUP_PREFIX}{stamp}-{slug(label)}" if label else f"{BACKUP_PREFIX}{stamp}"


# --------------------------------------------------------------------------- #
# Copia
# --------------------------------------------------------------------------- #
def backup_sqlite(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"No existe la base de datos SQLite: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source)) as origin, sqlite3.connect(str(target)) as destination:
        origin.backup(destination)


def backup_postgres(database_url: str, target: Path) -> None:
    executable = shutil.which("pg_dump")
    if executable is None:
        raise RuntimeError(
            "pg_dump no está instalado: instale postgresql-client o use una copia del volumen."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        subprocess.run(
            [executable, "--format=custom", "--no-owner", "--dbname", database_url],
            stdout=handle,
            check=True,
        )


def archive_storage(storage_dir: Path, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    files = 0
    with tarfile.open(target, "w:gz") as archive:
        if storage_dir.exists():
            for path in sorted(storage_dir.rglob("*")):
                if path.is_file():
                    files += 1
                    archive.add(path, arcname=str(Path(storage_dir.name) / path.relative_to(storage_dir)))
    return files


def create_backup(
    output_dir: Path,
    *,
    database_url: str | None = None,
    storage_dir: Path | None = None,
    keep: int | None = None,
    label: str | None = None,
    include_storage: bool = True,
    moment: datetime | None = None,
) -> Path:
    """Crea ``output_dir/aurora-<fecha>`` y devuelve su ruta."""
    database_url = database_url or settings.database_url
    storage_dir = Path(storage_dir or settings.storage_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / build_name(label, moment)
    if target.exists():
        raise FileExistsError(f"Ya existe una copia con ese nombre: {target}")
    target.mkdir(parents=True)

    manifest: dict[str, Any] = {
        "created_at": (moment or datetime.now(timezone.utc)).isoformat(),
        "label": label or "manual",
        "app_version": settings.app_version,
        "environment": settings.environment,
        "database": {},
        "storage": {},
        "generator": "scripts.backup",
    }

    source_db = sqlite_path(database_url)
    if source_db is not None:
        destination = target / "database.sqlite3"
        backup_sqlite(source_db, destination)
        engine = "sqlite"
        source_name = str(source_db)
    else:
        destination = target / "database.dump"
        backup_postgres(database_url, destination)
        engine = "postgresql"
        source_name = database_url.split("@")[-1]

    manifest["database"] = {
        "engine": engine,
        "source": source_name,
        "file": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }

    if include_storage:
        archive = target / "storage.tar.gz"
        files = archive_storage(storage_dir, archive)
        manifest["storage"] = {
            "source": str(storage_dir),
            "file": archive.name,
            "files": files,
            "bytes": archive.stat().st_size,
            "sha256": sha256_file(archive),
        }

    (target / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    if keep is not None and keep > 0:
        prune_backups(output_dir, keep)
    return target


# --------------------------------------------------------------------------- #
# Retención y consulta
# --------------------------------------------------------------------------- #
def list_backups(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted(
        (path for path in output_dir.iterdir() if path.is_dir() and path.name.startswith(BACKUP_PREFIX)),
        key=lambda path: path.name,
    )


def prune_backups(output_dir: Path, keep: int) -> list[Path]:
    backups = list_backups(output_dir)
    removable = backups[:-keep] if keep > 0 else backups
    for path in removable:
        shutil.rmtree(path)
    return removable


def read_manifest(backup_dir: Path) -> dict[str, Any]:
    manifest_path = Path(backup_dir) / MANIFEST
    if not manifest_path.exists():
        raise FileNotFoundError(f"La copia no contiene {MANIFEST}: {backup_dir}")
    return json.loads(manifest_path.read_text())


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    """Comprueba que los ficheros existen y conservan su huella."""
    manifest = read_manifest(backup_dir)
    for section in ("database", "storage"):
        entry = manifest.get(section) or {}
        if not entry:
            continue
        path = Path(backup_dir) / entry["file"]
        if not path.exists():
            raise FileNotFoundError(f"Falta {path.name} en {backup_dir}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"La huella de {path.name} no coincide con el manifiesto")
    return manifest


# --------------------------------------------------------------------------- #
# Restauración
# --------------------------------------------------------------------------- #
def restore_backup(
    backup_dir: Path,
    *,
    database_url: str | None = None,
    storage_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Restaura una copia sobre la base y el almacenamiento indicados."""
    database_url = database_url or settings.database_url
    storage_dir = Path(storage_dir or settings.storage_dir)
    manifest = verify_backup(backup_dir)

    target_db = sqlite_path(database_url)
    if target_db is not None:
        if target_db.exists() and not force:
            raise FileExistsError(
                f"Ya existe {target_db}; pare el servicio y repita con --force para sobrescribirla"
            )
        target_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(backup_dir) / manifest["database"]["file"], target_db)
        for suffix in ("-wal", "-shm"):
            sidecar = target_db.with_name(target_db.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
    else:
        executable = shutil.which("pg_restore")
        if executable is None:
            raise RuntimeError("pg_restore no está instalado: instale postgresql-client")
        subprocess.run(
            [executable, "--clean", "--if-exists", "--no-owner", "--dbname", database_url,
             str(Path(backup_dir) / manifest["database"]["file"])],
            check=True,
        )

    storage_entry = manifest.get("storage") or {}
    if storage_entry:
        extract_archive(Path(backup_dir) / storage_entry["file"], storage_dir.parent)
    return manifest


def extract_archive(archive_path: Path, destination: Path) -> None:
    """Extrae un tar.gz rechazando rutas absolutas o que salgan del destino."""
    destination = destination.resolve()
    root = str(destination) + os.sep
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != destination and not str(target).startswith(root):
                raise ValueError(f"Ruta insegura en el archivo: {member.name}")
        archive.extractall(path=destination)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def describe(backup_dir: Path) -> str:
    try:
        manifest = read_manifest(backup_dir)
    except (FileNotFoundError, json.JSONDecodeError):
        return f"{backup_dir.name}  (sin manifiesto legible)"
    database = manifest.get("database") or {}
    storage = manifest.get("storage") or {}
    return (
        f"{backup_dir.name}  {manifest.get('created_at', '?')}  "
        f"BD {database.get('engine', '?')} {database.get('bytes', 0) / 1024:.0f} KiB  "
        f"documentos {storage.get('files', 0)} ({storage.get('bytes', 0) / 1024:.0f} KiB)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copias de seguridad de AURORA")
    parser.add_argument("--output", type=Path, default=BACKEND_DIR / "backups",
                        help="Directorio donde guardar las copias")
    parser.add_argument("--database-url", default=None, help="URL de base de datos (por defecto la configurada)")
    parser.add_argument("--storage-dir", type=Path, default=None, help="Volumen de documentos")
    parser.add_argument("--keep", type=int, default=7, help="Copias a conservar (0 desactiva la retención)")
    parser.add_argument("--label", default=None, help="Etiqueta para identificar la copia")
    parser.add_argument("--no-storage", action="store_true", help="No incluir los documentos")
    parser.add_argument("--list", action="store_true", help="Listar copias existentes")
    parser.add_argument("--verify", type=Path, default=None, help="Verificar una copia concreta")
    parser.add_argument("--restore", type=Path, default=None, help="Restaurar una copia concreta")
    parser.add_argument("--force", action="store_true", help="Permitir sobrescribir al restaurar")
    args = parser.parse_args(argv)

    if args.list:
        backups = list_backups(args.output)
        if not backups:
            print(f"No hay copias en {args.output}")
        for path in backups:
            print(describe(path))
        return 0

    if args.verify:
        manifest = verify_backup(args.verify)
        print(f"OK: {args.verify.name} verificada ({manifest['created_at']})")
        return 0

    if args.restore:
        if os.environ.get("AURORA_RUNNING") == "1":
            print("Pare el servicio antes de restaurar (AURORA_RUNNING=1 detectado)", file=sys.stderr)
            return 2
        manifest = restore_backup(
            args.restore,
            database_url=args.database_url,
            storage_dir=args.storage_dir,
            force=args.force,
        )
        print(f"Restaurada {args.restore.name} ({manifest['created_at']})")
        return 0

    target = create_backup(
        args.output,
        database_url=args.database_url,
        storage_dir=args.storage_dir,
        keep=args.keep,
        label=args.label,
        include_storage=not args.no_storage,
    )
    manifest = verify_backup(target)
    print(f"Copia creada y verificada: {target}")
    print(f"  Base de datos: {manifest['database']['bytes'] / 1024:.0f} KiB")
    if manifest.get("storage"):
        print(f"  Documentos: {manifest['storage']['files']} ficheros")
    print(f"  Retención: {args.keep} copias en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
