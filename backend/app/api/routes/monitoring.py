"""Endpoint de métricas Prometheus con gauges de infraestructura y negocio."""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select, text

from app.core import metrics as registry
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import IncidentStatus, ReservationStatus, TaskStatus
from app.models import Delivery, Incident, Pallet, StockLevel, StockReservation, Task

logger = logging.getLogger("aurora.metrics")
settings = get_settings()

router = APIRouter(tags=["Observabilidad"])

OPEN_TASK_STATUSES = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)
OPEN_INCIDENT_STATUSES = (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED)


def _authorized(request: Request) -> bool:
    expected = settings.metrics_token
    if not expected:
        return True
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    return bool(token) and hmac.compare_digest(token, expected)


def storage_usage(path: Path) -> tuple[int, int]:
    """(bytes, ficheros) del volumen de documentos; 0 si no existe."""
    total = 0
    files = 0
    if not path.exists():
        return 0, 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            candidate = Path(root) / name
            try:
                total += candidate.stat().st_size
                files += 1
            except OSError:
                continue
    return total, files


def business_gauges() -> list[tuple[str, str, list[tuple[dict[str, str], float]]]]:
    """Consultas agregadas por scrape; si la base falla se devuelve solo el estado 0."""
    gauges: list[tuple[str, str, list[tuple[dict[str, str], float]]]] = []
    database_up = 1.0
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            pallets = [
                ({"status": str(status)}, float(count))
                for status, count in db.execute(
                    select(Pallet.status, func.count()).group_by(Pallet.status)
                ).all()
            ]
            deliveries = [
                ({"status": str(status)}, float(count))
                for status, count in db.execute(
                    select(Delivery.status, func.count()).group_by(Delivery.status)
                ).all()
            ]
            tasks_open = float(
                db.scalar(
                    select(func.count()).select_from(Task).where(Task.status.in_(OPEN_TASK_STATUSES))
                )
                or 0
            )
            incidents_open = float(
                db.scalar(
                    select(func.count())
                    .select_from(Incident)
                    .where(Incident.status.in_(OPEN_INCIDENT_STATUSES))
                )
                or 0
            )
            reservations_active = float(
                db.scalar(
                    select(func.count())
                    .select_from(StockReservation)
                    .where(StockReservation.status == ReservationStatus.ACTIVE)
                )
                or 0
            )
            stock_units = float(
                db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0))) or 0
            )
        gauges = [
            ("aurora_pallets_total", "Palés por estado.", pallets),
            ("aurora_deliveries_total", "Repartos por estado.", deliveries),
            ("aurora_tasks_open", "Tareas pendientes, en curso o bloqueadas.", [({}, tasks_open)]),
            ("aurora_incidents_open", "Incidencias abiertas o reconocidas.", [({}, incidents_open)]),
            ("aurora_reservations_active", "Reservas de stock activas.", [({}, reservations_active)]),
            ("aurora_stock_units_total", "Unidades físicas en existencias.", [({}, stock_units)]),
        ]
    except Exception:  # noqa: BLE001 - las métricas nunca deben tumbar el scrape
        database_up = 0.0
        logger.warning("No se pudieron calcular los gauges de negocio", exc_info=True)

    storage_bytes, storage_files = storage_usage(Path(settings.storage_dir))
    gauges += [
        ("aurora_database_up", "1 si la base de datos respondió a SELECT 1.", [({}, database_up)]),
        ("aurora_storage_bytes", "Tamaño del volumen de documentos en bytes.",
         [({}, float(storage_bytes))]),
        ("aurora_storage_files", "Número de ficheros en el volumen de documentos.",
         [({}, float(storage_files))]),
        ("aurora_metrics_protected", "1 si /metrics exige token Bearer.", [({}, 0.0 if not settings.metrics_token else 1.0)]),
        ("aurora_info", "Versión y entorno del despliegue.",
         [({"version": settings.app_version, "environment": settings.environment,
            "demo_mode": "true" if settings.demo_mode else "false"}, 1.0)]),
    ]
    return gauges


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request) -> Response:
    if not _authorized(request):
        return Response(
            content="unauthorized\n",
            status_code=401,
            media_type="text/plain; charset=utf-8",
            headers={"WWW-Authenticate": "Bearer"},
        )
    body = registry.render(business_gauges())
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
