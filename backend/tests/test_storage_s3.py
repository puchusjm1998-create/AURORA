"""Pruebas del adaptador S3 contra un servidor S3 local (moto)."""

from __future__ import annotations

import re
from datetime import date
from io import BytesIO

import boto3
import pytest
from botocore.client import Config as BotoConfig
from fastapi import UploadFile
from moto.server import ThreadedMotoServer
from starlette.datastructures import Headers

from app.services import s3 as s3_storage
from app.services import storage


@pytest.fixture()
def s3_server(tmp_path, monkeypatch):
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    suffix = re.sub(r"[^a-z0-9.-]", "-", tmp_path.name.lower())
    bucket = f"aurora-test-{suffix}"
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

    monkeypatch.setattr(storage.settings, "storage_backend", "s3")
    monkeypatch.setattr(storage.settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(storage.settings, "storage_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(storage.settings, "s3_bucket", bucket)
    monkeypatch.setattr(storage.settings, "s3_prefix", "aurora")
    monkeypatch.setattr(storage.settings, "s3_endpoint_url", endpoint)
    monkeypatch.setattr(storage.settings, "s3_region", "eu-west-1")
    monkeypatch.setattr(storage.settings, "s3_access_key_id", "test")
    monkeypatch.setattr(storage.settings, "s3_secret_access_key", "test")
    monkeypatch.setattr(storage.settings, "s3_addressing_style", "path")
    try:
        yield client, bucket, tmp_path
    finally:
        server.stop()


def _png() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (320, 120), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.anyio()
async def test_signature_roundtrip_through_s3(s3_server):
    client, bucket, tmp_path = s3_server
    png = _png()
    upload = UploadFile(
        file=BytesIO(png),
        filename="firma.png",
        headers=Headers({"content-type": "image/png"}),
    )
    stored = await storage.store_delivery_signature(upload, delivery_reference="AUR-DEL-900")
    assert stored.storage_backend == "s3"
    assert stored.absolute_path is None
    assert stored.relative_path.startswith("deliveries/AUR-DEL-900/")
    assert not (tmp_path / "storage" / stored.relative_path).exists()

    obj = client.get_object(Bucket=bucket, Key=f"aurora/{stored.relative_path}")
    assert obj["ContentType"] == "image/png"
    assert obj["Metadata"]["sha256"] == stored.sha256

    cached = storage.resolve_stored_path(stored.relative_path)
    assert cached.is_file()
    assert cached.read_bytes() == png
    # Segunda resolución usa la caché, no vuelve a descargar.
    assert storage.resolve_stored_path(stored.relative_path) == cached


@pytest.mark.anyio()
async def test_invoice_upload_and_missing_key(s3_server):
    client, bucket, _ = s3_server
    pdf = b"%PDF-1.4\n% AURORA test\n"
    upload = UploadFile(
        file=BytesIO(pdf),
        filename="factura.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )
    stored = await storage.store_invoice_file(
        upload,
        invoice_date=date(2026, 11, 18),
        supplier="Proveedor S3",
        number="F-2026-99",
    )
    assert stored.storage_backend == "s3"
    assert stored.sha256 and stored.size == len(pdf)
    obj = client.get_object(Bucket=bucket, Key=f"aurora/{stored.relative_path}")
    assert obj["Body"].read() == pdf

    with pytest.raises(Exception) as exc:
        storage.resolve_stored_path("invoices/2026/11/18/NO-EXISTE/factura.pdf")
    assert getattr(exc.value, "code", None) == "file_missing"

    status = s3_storage.status()
    assert status["backend"] == "s3"
    assert status["reachable"] is True
