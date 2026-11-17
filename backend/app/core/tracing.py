"""Trazas distribuidas OpenTelemetry (opt-in).

Se activa con ``AURORA_TRACING_ENABLED=true``. Exporta por OTLP/HTTP
(``OTLP_ENDPOINT`` o variables estándar ``OTEL_EXPORTER_OTLP_*``) o por consola
para desarrollo. Instrumenta FastAPI y SQLAlchemy, propaga el contexto W3C
(``traceparent``) y expone ``X-Trace-ID`` para correlacionar con los logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased
from opentelemetry.trace import SpanKind
from sqlalchemy import event

from app.core.config import get_settings

logger = logging.getLogger("aurora.tracing")

EXPORTED_URLS = "metrics,healthz"


@dataclass
class TracingState:
    provider: TracerProvider | None = None
    exporter: str | None = None
    app_instrumented: bool = False


_state = TracingState()


def current_trace_id() -> str | None:
    """Trace ID W3C de la petición actual, si hay una traza activa."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def build_provider(
    exporter: SpanExporter,
    *,
    exporter_name: str,
    ratio: float = 1.0,
) -> TracerProvider:
    settings = get_settings()
    resource = Resource.create(
        {
            "service.name": settings.tracing_service_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.environment,
        }
    )
    sampler = ALWAYS_ON if ratio >= 1.0 else ParentBased(TraceIdRatioBased(max(0.0, ratio)))
    provider = TracerProvider(resource=resource, sampler=sampler)
    if exporter_name in ("console", "memory"):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def _build_exporter() -> tuple[SpanExporter, str] | None:
    settings = get_settings()
    name = settings.tracing_exporter.strip().lower()
    if name == "console":
        return ConsoleSpanExporter(), "console"
    if name == "otlp":
        endpoint = settings.otlp_endpoint.strip() or None
        return (
            OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter(),
            "otlp",
        )
    logger.warning("Exportador de trazas desconocido: %s (se desactiva)", name)
    return None


def instrument_sqlalchemy(engine, provider: TracerProvider) -> None:
    """Spans de SQL compatibles con SQLAlchemy 2.1.

    El instrumentador oficial aún limita a SQLAlchemy < 2.1; se enganchan los
    eventos del motor y se registra la sentencia (sin parámetros) como atributo.
    """
    tracer = provider.get_tracer("aurora.sqlalchemy")
    if getattr(engine, "_aurora_tracing_installed", False):
        return
    engine._aurora_tracing_installed = True  # type: ignore[attr-defined]

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        operation = (statement.lstrip().split(" ", 1)[0] or "SQL").upper()
        manager = tracer.start_as_current_span(f"sql.{operation.lower()}", kind=SpanKind.CLIENT)
        span = manager.__enter__()
        span.set_attribute("db.system", "sqlite" if "sqlite" in str(engine.url) else "postgresql")
        span.set_attribute("db.operation", operation)
        span.set_attribute("db.statement", " ".join(statement.split())[:500])
        span.set_attribute("db.executemany", bool(executemany))
        conn.info.setdefault("_aurora_sql_spans", []).append(manager)

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        stack = conn.info.get("_aurora_sql_spans") or []
        if stack:
            stack.pop().__exit__(None, None, None)

    @event.listens_for(engine, "handle_error")
    def _error(exception_context):  # noqa: ANN001
        conn = exception_context.connection
        stack = getattr(conn, "info", {}).get("_aurora_sql_spans", []) if conn else []
        if stack:
            stack.pop().__exit__(type(exception_context.original_exception),
                                  exception_context.original_exception, None)


def configure_tracing(
    app,
    *,
    engine=None,
    exporter: SpanExporter | None = None,
    exporter_name: str | None = None,
    ratio: float | None = None,
    force: bool = False,
) -> TracerProvider | None:
    """Activa la instrumentación. Sin configuración explícita es no-op."""
    settings = get_settings()
    if _state.provider is not None:
        return _state.provider
    if exporter is None:
        if not (force or settings.tracing_enabled):
            return None
        built = _build_exporter()
        if built is None:
            return None
        exporter, exporter_name = built
    exporter_name = exporter_name or "memory"
    provider = build_provider(
        exporter,
        exporter_name=exporter_name,
        ratio=settings.tracing_sample_ratio if ratio is None else ratio,
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls=EXPORTED_URLS
    )
    if engine is not None:
        instrument_sqlalchemy(engine, provider)
    _state.provider = provider
    _state.exporter = exporter_name
    _state.app_instrumented = True
    logger.info(
        "Trazas OpenTelemetry activas (exportador=%s, muestreo=%.2f)",
        exporter_name,
        settings.tracing_sample_ratio if ratio is None else ratio,
    )
    return provider


def shutdown_tracing() -> None:
    if _state.provider is not None:
        _state.provider.shutdown()
        _state.provider = None
        _state.app_instrumented = False


def reset_tracing_for_tests() -> None:
    """Apaga el proveedor y limpia el estado (solo pruebas)."""
    shutdown_tracing()
    _state.exporter = None


def tracing_status() -> dict[str, object]:
    settings = get_settings()
    return {
        "enabled": bool(_state.provider) or settings.tracing_enabled,
        "active": bool(_state.provider),
        "exporter": _state.exporter or (settings.tracing_exporter if settings.tracing_enabled else None),
        "sample_ratio": settings.tracing_sample_ratio,
        "service_name": settings.tracing_service_name,
    }
