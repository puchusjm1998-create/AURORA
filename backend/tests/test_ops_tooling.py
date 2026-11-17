"""Pruebas de las herramientas de operación: copias y métricas de carga."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.backup import (
    create_backup,
    list_backups,
    prune_backups,
    read_manifest,
    restore_backup,
    sha256_file,
    verify_backup,
)
from scripts.load_test import percentile


def _make_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE pallets (code TEXT PRIMARY KEY, units INTEGER)")
        connection.execute("INSERT INTO pallets VALUES ('AUR-PAL-000001', 20)")
        connection.commit()


def test_backup_creates_verified_manifest_with_hashes(tmp_path: Path) -> None:
    database = tmp_path / "aurora.db"
    _make_database(database)
    storage = tmp_path / "storage"
    (storage / "invoices").mkdir(parents=True)
    (storage / "invoices" / "factura.txt").write_text("documento original")

    target = create_backup(
        tmp_path / "backups",
        database_url=f"sqlite:///{database}",
        storage_dir=storage,
        label="prueba",
        keep=3,
    )

    manifest = read_manifest(target)
    assert manifest["label"] == "prueba"
    assert manifest["database"]["engine"] == "sqlite"
    assert manifest["storage"]["files"] == 1
    copy = target / manifest["database"]["file"]
    assert sha256_file(copy) == manifest["database"]["sha256"]
    with sqlite3.connect(copy) as connection:
        assert connection.execute("SELECT units FROM pallets").fetchone() == (20,)

    # La verificación detecta manipulación del contenido.
    copy.write_bytes(copy.read_bytes() + b"x")
    with pytest.raises(ValueError):
        verify_backup(target)


def test_retention_keeps_the_newest_copies(tmp_path: Path) -> None:
    database = tmp_path / "aurora.db"
    _make_database(database)
    output = tmp_path / "backups"
    for index in range(3):
        create_backup(
            output,
            database_url=f"sqlite:///{database}",
            include_storage=False,
            label=f"copia-{index}",
        )

    assert len(list_backups(output)) == 3
    removed = prune_backups(output, 2)
    assert len(removed) == 1
    assert "copia-0" in removed[0].name
    assert len(list_backups(output)) == 2


def test_restore_recovers_database_and_documents(tmp_path: Path) -> None:
    database = tmp_path / "aurora.db"
    _make_database(database)
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "albaran.txt").write_text("firma del cliente")

    backup = create_backup(
        tmp_path / "backups",
        database_url=f"sqlite:///{database}",
        storage_dir=storage,
        label="restauracion",
    )

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM pallets")
        connection.commit()
    (storage / "albaran.txt").unlink()

    with pytest.raises(FileExistsError):
        restore_backup(backup, database_url=f"sqlite:///{database}", storage_dir=storage)

    manifest = restore_backup(
        backup,
        database_url=f"sqlite:///{database}",
        storage_dir=storage,
        force=True,
    )
    assert manifest["label"] == "restauracion"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT code FROM pallets").fetchone() == ("AUR-PAL-000001",)
    assert (storage / "albaran.txt").read_text() == "firma del cliente"

    manifest_file = backup / "manifest.json"
    assert json.loads(manifest_file.read_text())["database"]["sha256"]


def test_percentile_interpolates_and_handles_edges() -> None:
    assert percentile([], 0.95) == 0.0
    assert percentile([42.0], 0.99) == 42.0
    values = [float(value) for value in range(1, 101)]
    assert percentile(values, 0.50) == pytest.approx(50.5)
    assert percentile(values, 0.95) == pytest.approx(95.05)
    assert percentile(values, 1.0) == 100.0


def test_restore_creates_the_target_directory(tmp_path: Path) -> None:
    database = tmp_path / "origen.db"
    _make_database(database)
    backup = create_backup(
        tmp_path / "backups",
        database_url=f"sqlite:///{database}",
        include_storage=False,
        label="destino-nuevo",
    )
    nested = tmp_path / "restaurado" / "sub" / "aurora.db"
    restore_backup(backup, database_url=f"sqlite:///{nested}", force=True)
    assert nested.exists()
    with sqlite3.connect(nested) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pallets").fetchone() == (1,)
