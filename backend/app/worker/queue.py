"""Estado y envío de tareas a la cola Celery/Redis."""

from __future__ import annotations

from typing import Any

from celery.result import AsyncResult
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import AppError
from app.worker.celery_app import celery_app
from app.worker.tasks import ping_task

settings = get_settings()
_EAGER_RESULTS: dict[str, Any] = {}


def broker_available() -> bool:
    try:
        client = Redis.from_url(
            settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        return bool(client.ping())
    except (RedisError, OSError, ValueError):
        return False


def worker_online(timeout: float = 0.4) -> bool:
    if settings.celery_task_always_eager:
        return True
    try:
        return bool(celery_app.control.ping(timeout=timeout))
    except Exception:  # noqa: BLE001 - un broker caído no debe tumbar /system
        return False


def status() -> dict[str, Any]:
    online = worker_online()
    available = broker_available()
    return {
        "enabled": not settings.celery_task_always_eager,
        "eager": settings.celery_task_always_eager,
        "broker_available": available,
        "worker_online": online,
        "broker": "redis" if settings.redis_url.startswith("redis") else "otro",
        "task": "aurora.ping",
        "message": (
            "Cola lista: Redis y un worker Celery responden."
            if available and online
            else "La cola no está lista; configure REDIS_URL y arranque el worker Celery."
        ),
    }


def enqueue_ping() -> tuple[str, str]:
    if not settings.celery_task_always_eager and not broker_available():
        raise AppError(
            "Redis no está disponible; no se puede encolar la tarea.",
            status_code=503,
            code="queue_unavailable",
        )
    try:
        result = ping_task.apply() if settings.celery_task_always_eager else ping_task.delay()
        if settings.celery_task_always_eager:
            _EAGER_RESULTS[result.id] = result
    except Exception as exc:  # noqa: BLE001 - broker caído o credenciales
        raise AppError(
            "No se pudo encolar la tarea en Celery.",
            status_code=503,
            code="queue_unavailable",
            details={"error": str(exc)[:300]},
        ) from exc
    return result.id, result.state


def task_status(task_id: str) -> dict[str, Any]:
    try:
        result = _EAGER_RESULTS.get(task_id) or AsyncResult(task_id, app=celery_app)
        ready = result.ready()
        successful = result.successful() if ready else None
        payload: dict[str, Any] = {
            "task_id": task_id,
            "state": result.state,
            "ready": ready,
            "successful": successful,
            "result": result.result if ready and successful else None,
        }
        if result.failed():
            payload["error"] = str(result.result)[:1000]
        return payload
    except Exception as exc:  # noqa: BLE001 - backend de resultados caído
        raise AppError(
            "No se pudo consultar la tarea en el backend de resultados.",
            status_code=503,
            code="queue_unavailable",
            details={"error": str(exc)[:300]},
        ) from exc
