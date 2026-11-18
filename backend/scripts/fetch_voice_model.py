"""Descarga el modelo Piper español y verifica su integridad.

Uso:
    python scripts/fetch_voice_model.py [--force]

El bundle de origen es el repositorio público ``dbranco/lumbre-voices``. Se
descargan solo los dos ficheros del modelo (ONNX y su configuración), no el
repositorio completo en disco. El SHA-256 del ONNX está fijado aquí: si el
origen cambia, el script falla en lugar de instalar un modelo distinto.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

BUNDLE_URL = os.environ.get(
    "AURORA_PIPER_BUNDLE_URL",
    "https://codeload.github.com/dbranco/lumbre-voices/tar.gz/refs/heads/main",
)
FILES = {
    "es_ES-davefx-medium.onnx": "6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917",
    "es_ES-davefx-medium.onnx.json": "0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842",
}
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "models"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _already_valid(target: Path, expected: str) -> bool:
    if not target.is_file():
        return False
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def _extract(archive: Path, destination: Path, force: bool) -> None:
    pending = {
        name: expected
        for name, expected in FILES.items()
        if force or not _already_valid(destination / name, expected)
    }
    if not pending:
        print(f"Modelo ya presente y verificado en {destination}")
        return
    with tarfile.open(archive, "r:gz") as tar:
        members = {
            Path(member.name).name: member
            for member in tar.getmembers()
            if member.isfile() and Path(member.name).name in pending
        }
        missing = sorted(set(pending) - set(members))
        if missing:
            raise SystemExit(f"El bundle no contiene: {', '.join(missing)}")
        for name, expected in pending.items():
            source = tar.extractfile(members[name])
            if source is None:
                raise SystemExit(f"No se pudo leer {name} del bundle")
            data = source.read()
            actual = _sha256(data)
            if actual != expected:
                raise SystemExit(
                    f"SHA-256 inesperado para {name}: {actual} != {expected}"
                )
            destination.mkdir(parents=True, exist_ok=True)
            temp = destination / f".{name}.part"
            temp.write_bytes(data)
            temp.replace(destination / name)
            print(f"Instalado {name} ({len(data) / 1_048_576:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="reextraer aunque exista")
    parser.add_argument("--url", default=BUNDLE_URL, help="URL del tar.gz del bundle")
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="directorio destino")
    args = parser.parse_args()
    destination = Path(args.dir)
    if not args.force and all(
        _already_valid(destination / name, digest) for name, digest in FILES.items()
    ):
        print(f"Modelo ya presente y verificado en {destination}")
        return 0
    print(f"Descargando {args.url} …")
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp:
        archive = Path(temp.name)
        with urllib.request.urlopen(args.url, timeout=300) as response:
            while chunk := response.read(1024 * 1024):
                temp.write(chunk)
    try:
        _extract(archive, destination, args.force)
    finally:
        archive.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
