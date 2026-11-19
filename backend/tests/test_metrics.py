"""Métricas Prometheus: exposición, histograma y protección por token."""

from __future__ import annotations

from app.api.routes import monitoring
from app.core import metrics
from app.core.metrics import BUCKETS


def _value(body: str, series: str) -> float:
    for line in body.splitlines():
        if line.startswith(series + " "):
            return float(line.split()[-1])
    raise AssertionError(f"Serie no encontrada: {series}\n{body[:800]}")


def test_metrics_exposes_http_and_business_series(admin_client):
    metrics.reset()
    assert admin_client.get("/api/v1/dashboard").status_code == 200

    response = admin_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert response.headers["cache-control"] == "no-store"
    body = response.text

    assert "# HELP aurora_http_requests_total" in body
    assert (
        'aurora_http_requests_total{method="GET",route="/api/v1/dashboard",status="200"} 1'
        in body
    )
    assert "# TYPE aurora_http_request_duration_seconds histogram" in body
    assert 'aurora_http_request_duration_seconds_bucket{le="+Inf",method="GET",route="/api/v1/dashboard"}' in body
    assert 'aurora_http_request_duration_seconds_count{method="GET",route="/api/v1/dashboard"} 1' in body
    assert _value(body, "aurora_database_up") == 1
    assert _value(body, "aurora_metrics_protected") == 0
    assert "aurora_info{" in body and 'environment="test"' in body and 'version="' in body
    assert _value(body, "aurora_stock_units_total") >= 0
    assert "# HELP aurora_pallets_total" in body
    # El propio scrape está en curso, así que el gauge vale al menos 1.
    assert _value(body, "aurora_http_requests_in_flight") >= 1
    # El propio scrape no se contabiliza para no inflar las series.
    assert 'route="/metrics"' not in body


def test_metrics_token_requires_bearer(admin_client, monkeypatch):
    monkeypatch.setattr(monitoring.settings, "metrics_token", "token-de-prueba-123")

    unauthenticated = admin_client.get("/metrics")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"

    wrong = admin_client.get("/metrics", headers={"Authorization": "Bearer incorrecto"})
    assert wrong.status_code == 401

    allowed = admin_client.get(
        "/metrics", headers={"Authorization": "Bearer token-de-prueba-123"}
    )
    assert allowed.status_code == 200
    assert "token-de-prueba-123" not in allowed.text
    assert _value(allowed.text, "aurora_metrics_protected") == 1


def test_histogram_accumulates_buckets_sum_and_count():
    metrics.reset()
    metrics.request_started()
    assert metrics.in_flight() == 1
    metrics.observe_request("GET", "/prueba", 200, 0.03)
    metrics.observe_request("POST", "/prueba", 500, 1.2)
    metrics.request_finished()
    assert metrics.in_flight() == 0

    body = metrics.render()
    assert (
        'aurora_http_requests_total{method="POST",route="/prueba",status="500"} 1' in body
    )
    bounds = [bucket for bucket in BUCKETS]
    first = body.split('le="0.05"', 1)[1].splitlines()[0].split()[-1]
    assert first == "1"
    assert _value(
        body,
        'aurora_http_request_duration_seconds_bucket{le="+Inf",method="GET",route="/prueba"}',
    ) == 1
    assert _value(
        body, 'aurora_http_request_duration_seconds_sum{method="GET",route="/prueba"}'
    ) == 0.03
    assert _value(
        body, 'aurora_http_request_duration_seconds_count{method="GET",route="/prueba"}'
    ) == 1
    assert len(bounds) == 11


def test_storage_usage_counts_files_and_bytes(tmp_path):
    (tmp_path / "invoices").mkdir()
    (tmp_path / "invoices" / "a.pdf").write_bytes(b"x" * 120)
    (tmp_path / "b.txt").write_bytes(b"y" * 30)
    total, files = monitoring.storage_usage(tmp_path)
    assert files == 2
    assert total == 150
    assert monitoring.storage_usage(tmp_path / "no-existe") == (0, 0)


def test_storage_metrics_uses_s3_bucket_and_cache(monkeypatch):
    monkeypatch.setattr(monitoring.settings, "storage_backend", "s3")
    monkeypatch.setattr(
        monitoring.s3_storage,
        "iter_objects",
        lambda prefix="": [("aurora/a.pdf", 120), ("aurora/b.png", 30)],
    )
    monkeypatch.setattr(monitoring, "_STORAGE_CACHE", (0.0, (0, 0)))
    assert monitoring.storage_metrics() == (150, 2)
    # La segunda llamada usa la caché y no vuelve a listar el bucket.
    monkeypatch.setattr(
        monitoring.s3_storage,
        "iter_objects",
        lambda prefix="": (_ for _ in ()).throw(AssertionError("no debe listar")),
    )
    assert monitoring.storage_metrics() == (150, 2)


def test_storage_metrics_falls_back_to_cache_on_s3_error(monkeypatch):
    monkeypatch.setattr(monitoring.settings, "storage_backend", "s3")
    monkeypatch.setattr(monitoring, "_STORAGE_CACHE", (1.0, (999, 7)))
    monkeypatch.setattr(
        monitoring,
        "_STORAGE_TTL",
        0.0,
    )
    monkeypatch.setattr(
        monitoring.s3_storage,
        "iter_objects",
        lambda prefix="": (_ for _ in ()).throw(RuntimeError("S3 caído")),
    )
    assert monitoring.storage_metrics() == (999, 7)
