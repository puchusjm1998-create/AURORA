"""Cola Celery: estado, permisos y ejecución eager en pruebas."""

from __future__ import annotations

from app.worker import queue
from app.worker.celery_app import celery_app


def test_queue_status_and_eager_ping(admin_client, worker_client, monkeypatch):
    monkeypatch.setattr(queue.settings, "celery_task_always_eager", True)
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)

    status = admin_client.get("/api/v1/system/queue")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["eager"] is True
    assert body["worker_online"] is True
    assert body["task"] == "aurora.ping"

    assert worker_client.get("/api/v1/system/queue").status_code == 200
    assert worker_client.post("/api/v1/system/queue/ping").status_code == 403

    enqueued = admin_client.post("/api/v1/system/queue/ping")
    assert enqueued.status_code == 200, enqueued.text
    task_id = enqueued.json()["task_id"]

    result = admin_client.get(f"/api/v1/system/queue/{task_id}")
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["state"] == "SUCCESS"
    assert payload["successful"] is True
    assert payload["result"]["status"] == "ok"
