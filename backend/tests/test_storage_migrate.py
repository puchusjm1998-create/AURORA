"""Migración local → S3 idempotente con verificación de huellas."""

from __future__ import annotations

import boto3
from botocore.client import Config as BotoConfig
from moto.server import ThreadedMotoServer

from app.services import storage
from scripts import storage_migrate


def test_migrate_local_files_and_skip_second_run(tmp_path, monkeypatch):
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    bucket = "aurora-migrate"
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
    settings = storage.settings
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", bucket)
    monkeypatch.setattr(settings, "s3_prefix", "aurora")
    monkeypatch.setattr(settings, "s3_endpoint_url", endpoint)
    monkeypatch.setattr(settings, "s3_region", "eu-west-1")
    monkeypatch.setattr(settings, "s3_access_key_id", "test")
    monkeypatch.setattr(settings, "s3_secret_access_key", "test")
    monkeypatch.setattr(settings, "s3_addressing_style", "path")

    source = tmp_path / "storage"
    (source / "invoices" / "2026").mkdir(parents=True)
    (source / "invoices" / "2026" / "factura.pdf").write_bytes(b"%PDF-migrado")
    (source / "deliveries").mkdir()
    (source / "deliveries" / "firma.png").write_bytes(b"\x89PNGfirma")
    (source / "invoices" / "ignorado.part").write_bytes(b"temporal")

    stats = storage_migrate.migrate(source, verify=True)
    assert stats["uploaded"] == 2
    assert stats["errors"] == []
    keys = {
        item["Key"] for item in client.list_objects_v2(Bucket=bucket)["Contents"]
    }
    assert keys == {
        "aurora/invoices/2026/factura.pdf",
        "aurora/deliveries/firma.png",
    }
    obj = client.get_object(Bucket=bucket, Key="aurora/invoices/2026/factura.pdf")
    assert obj["ContentType"] == "application/pdf"
    assert obj["Metadata"]["sha256"]

    second = storage_migrate.migrate(source, verify=True)
    assert second["uploaded"] == 0
    assert second["skipped"] == 2
    server.stop()
