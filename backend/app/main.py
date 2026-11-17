"""AURORA LOGISTICS AI — FastAPI application entry point.

In production the same process serves the compiled Next.js frontend (static
export) and the REST API, which keeps cookies first-party and removes the need
for a proxy. During development the Next.js dev server can proxy /api to this
application instead.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.exc import IntegrityError

from app.api.router import api_router
from app.api.routes import monitoring
from app.core import metrics as metrics_registry
from app.core.config import REPO_DIR, get_settings
from app.core.errors import AppError
from app.core.timeutils import utcnow

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("aurora")

FRONTEND_OUT = REPO_DIR / "frontend" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.assert_safe()
    if settings.bootstrap:
        from app.db.init import initialize_database

        initialize_database(migrate=settings.run_migrations)
        logger.info("AURORA bootstrap completado (%s)", settings.environment)
    if FRONTEND_OUT.exists():
        logger.info("Frontend compilado disponible en %s", FRONTEND_OUT)
    else:
        logger.warning(
            "No se encontró el frontend compilado en %s. Ejecute 'npm run build' en frontend/.",
            FRONTEND_OUT,
        )
    yield


def _route_template(request: Request) -> str:
    """Ruta con parámetros sustituidos por su nombre, para acotar la cardinalidad.

    El ``route.path`` de FastAPI no incluye el prefijo del router, así que se parte
    de la ruta real y se reemplazan los valores de ``path_params``. El comodín del
    frontend estático se agrupa como ``frontend`` para no crear una serie por página.
    """
    route = request.scope.get("route")
    declared = getattr(route, "path", None)
    if not declared:
        return "unmatched"
    if "full_path" in declared:
        return "frontend"
    path = request.url.path
    for name, value in (request.scope.get("path_params") or {}).items():
        if value:
            path = path.replace(str(value), f"{{{name}}}")
    return path


app = FastAPI(
    title="AURORA LOGISTICS AI",
    version=settings.app_version,
    description=(
        "API de gestión logística: inventario, trazabilidad QR, palés, movimientos, "
        "facturas, personal y auditoría. Los permisos se comprueban siempre en el servidor."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Requested-With"],
        max_age=600,
    )


@app.middleware("http")
async def request_context(request: Request, call_next) -> Response:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    metrics_registry.request_started()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        metrics_registry.observe_request(
            request.method, _route_template(request), 500, elapsed_ms / 1000
        )
        logger.exception("Error no controlado [%s] %s %s", request_id, request.method, request.url.path)
        raise
    finally:
        metrics_registry.request_finished()
    elapsed_ms = (time.perf_counter() - started) * 1000
    if request.url.path != "/metrics":
        metrics_registry.observe_request(
            request.method, _route_template(request), response.status_code, elapsed_ms / 1000
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        logger.info(
            "%s %s -> %s (%.1f ms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []) if part not in ("body", "query"))
        fields.append({"field": location, "message": error.get("msg", "Valor no válido")})
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Los datos enviados no son válidos.",
                "details": {"fields": fields},
            }
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    logger.warning("Conflicto de integridad en %s: %s", request.url.path, exc.orig)
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "integrity_conflict",
                "message": "La operación entra en conflicto con datos existentes o con una restricción.",
                "details": None,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error interno en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Se ha producido un error interno. Consulte el identificador de la solicitud.",
                "details": {"request_id": request.headers.get("x-request-id")},
            }
        },
    )


app.include_router(api_router)
app.include_router(monitoring.router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok", "time": utcnow().isoformat()}


# ---------------------------------------------------------------------------
# Static frontend (Next.js static export): exact routes, no SPA rewrite
# ---------------------------------------------------------------------------
def _serve_static(full_path: str) -> Response:
    if not FRONTEND_OUT.exists():
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "frontend_not_built",
                    "message": "El frontend no está compilado. Ejecute 'npm run build' en frontend/.",
                    "details": None,
                }
            },
        )
    root = FRONTEND_OUT.resolve()
    relative = full_path.strip("/")
    candidates = []
    if relative:
        base = (root / relative).resolve()
        candidates.extend([base, base / "index.html", base.with_suffix(".html")])
    else:
        candidates.append(root / "index.html")

    for candidate in candidates:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            if candidate.suffix == ".html":
                return FileResponse(candidate, headers={"Cache-Control": "no-store"})
            cache = "public, max-age=31536000, immutable" if "/_next/static/" in str(candidate) else "public, max-age=3600"
            return FileResponse(candidate, headers={"Cache-Control": cache})

    fallback = root / "404.html"
    if fallback.is_file():
        return FileResponse(fallback, status_code=404)
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "not_found", "message": "Recurso no encontrado.", "details": None}},
    )


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str) -> Response:
    if full_path.startswith(("api/", "healthz")):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "Recurso no encontrado.", "details": None}},
        )
    return _serve_static(full_path or "index.html")
