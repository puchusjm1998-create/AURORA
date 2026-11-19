"""Aplicación Celery de AURORA.

El API sigue funcionando sin Redis; la cola solo se usa para tareas de fondo.
Arranque del worker y del planificador (procesos separados):

    celery -A app.worker.celery_app worker --loglevel=info
    celery -A app.worker.celery_app beat --loglevel=info
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aurora",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.warehouse_timezone,
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=max(30, settings.celery_task_time_limit - 15),
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
    worker_prefetch_multiplier=1,
    result_expires=3600,
)

celery_app.conf.beat_schedule = {
    "evaluar-alertas-cada-5-minutos": {
        "task": "aurora.evaluate_alerts",
        "schedule": schedule(run_every=300),
    },
    "enviar-informes-cada-5-minutos": {
        "task": "aurora.send_scheduled_reports",
        "schedule": schedule(run_every=300),
    },
}
