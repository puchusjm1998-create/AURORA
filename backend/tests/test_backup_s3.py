"""Copias de seguridad con documentos en S3: archivo, manifiesto y restauración."""

from __future__ import annotations

import tarfile

import boto3
from botocore.client import Config as BotoConfig
from moto.server import ThreadedMotoServer

from app.services import s3 as s3_storage
from app.services import storage
from scripts import backup


def test_s3_backup_and_restore_roundtrip(db, tmp_path, monkeypatch):
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    bucket = "aurora-backup"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="eu-west-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=BotoConfig(s3={"addressing_style": "path"}),
    )
    client.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )
    monkeypatch.setattr(settings := storage.settings, "storage_backend", "s3")
    monkeypatch.setattr(backup.settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", bucket)
    monkeypatch.setattr(settings, "s3_prefix", "aurora")
    monkeypatch.setattr(settings, "s3_endpoint_url", endpoint)
    monkeypatch.setattr(settings, "s3_region", "eu-west-1")
    monkeypatch.setattr(settings, "s3_access_key_id", "test")
    monkeypatch.setattr(settings, "s3_secret_access_key", "test")
    monkeypatch.setattr(settings, "s3_addressing_style", "path")

    documents = {
        "invoices/2026/11/18/PROVEEDOR/F-1/abc-FACTURA.pdf": b"%PDF-1.4 copia",
        "deliveries/AUR-DEL-1/signature-def.png": b"\x89PNG\r\n\x1a\nfirma",
    }
    for relative, payload in documents.items():
        s3_storage.upload_bytes(payload, relative, content_type="application/pdf")

    created = backup.create_backup(
        tmp_path / "backups",
        database_url=settings.database_url,
        storage_backend="s3",
        label="s3",
    )
    manifest = backup.verify_backup(created)
    assert manifest["storage"]["backend"] == "s3"
    assert manifest["storage"]["files"] == 2
    assert manifest["storage"]["source"].startswith("s3://aurora-backup/")

    with tarfile.open(created / "storage.tar.gz", "r:gz") as archive:
        names = set(archive.getnames())
        assert "storage/invoices/2026/11/18/PROVEEDOR/F-1/abc-FACTURA.pdf" in names
        assert "storage/deliveries/AUR-DEL-1/signature-def.png" in names

    for key in list(documents):
        client.delete_object(Bucket=bucket, Key=f"aurora/{key}")
    assert client.list_objects_v2(Bucket=bucket).get("Contents", []) == []

    target_db = tmp_path / "restored.db"
    restored = backup.restore_backup(
        created, database_url=f"sqlite:///{target_db}", force=True
    )
    assert restored["storage"]["files"] == 2
    keys = {
        item["Key"] for item in client.list_objects_v2(Bucket=bucket)["Contents"]
    }
    assert keys == {f"aurora/{key}" for key in documents}
    for relative, payload in documents.items():
        obj = client.get_object(Bucket=bucket, Key=f"aurora/{relative}")
        assert obj["Body"].read() == payload
        assert obj["Metadata"]["sha256"]
    server.stop()
