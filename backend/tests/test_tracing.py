"""Trazas OpenTelemetry: spans, contexto W3C y cabecera de correlación."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import tracing
from app.core.tracing import configure_tracing, current_trace_id, tracing_status


def _mini_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str | None]:
        return {"trace_id": current_trace_id()}

    return app


def test_instrumentation_exports_server_span_and_propagates_context():
    tracing.reset_tracing_for_tests()
    exporter = InMemorySpanExporter()
    app = _mini_app()
    provider = configure_tracing(
        app, exporter=exporter, exporter_name="memory", ratio=1.0, force=True
    )
    assert provider is not None
    assert tracing_status()["active"] is True

    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with TestClient(app) as client:
        response = client.get("/ping", headers={"traceparent": traceparent})
    assert response.status_code == 200
    assert response.json()["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"

    spans = exporter.get_finished_spans()
    assert spans, "No se exportó ningún span"
    server = next(span for span in spans if "/ping" in span.name)
    assert server.name.startswith("GET /ping")
    assert server.context is not None
    assert format(server.context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
    attributes = dict(server.attributes or {})
    status = attributes.get("http.status_code", attributes.get("http.response.status_code"))
    assert status == 200

    tracing.reset_tracing_for_tests()
    assert tracing_status()["active"] is False


def test_tracing_is_disabled_by_default(monkeypatch):
    tracing.reset_tracing_for_tests()
    monkeypatch.setattr(tracing.get_settings(), "tracing_enabled", False)
    assert configure_tracing(_mini_app()) is None
    assert current_trace_id() is None


def test_main_app_sets_trace_header_when_there_is_a_span(client, monkeypatch):
    import app.main as main

    expected = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(main, "current_trace_id", lambda: expected)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["x-trace-id"] == expected


def test_main_app_omits_trace_header_without_span(client, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "current_trace_id", lambda: None)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert "x-trace-id" not in response.headers
