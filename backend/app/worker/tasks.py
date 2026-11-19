"""Tareas de fondo: alertas, informes programados y comprobación de la cola."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone

from app.core.db import SessionLocal
from app.services.alerts import evaluate_rules
from app.services.report_delivery import due_schedules, process_due, smtp_status
from app.worker.celery_app import celery_app


@celery_app.task(name="aurora.ping")
def ping_task() -> dict[str, str]:
    return {
        "status": "ok",
        "worker": socket.gethostname(),
        "pid": str(os.getpid()),
        "time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@celery_app.task(name="aurora.evaluate_alerts")
def evaluate_alerts_task() -> dict[str, object]:
    with SessionLocal() as db:
        result = evaluate_rules(db)
        db.commit()
        alerts = [
            {
                "id": alert.id,
                "severity": alert.severity.value,
                "message": alert.message,
                "notified": alert.notified_at is not None,
            }
            for alert in result["alerts"]  # type: ignore[index]
        ]
    return {
        "evaluated": result["evaluated"],
        "triggered": result["triggered"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "alerts": alerts,
    }


@celery_app.task(name="aurora.send_scheduled_reports")
def send_scheduled_reports_task(limit: int | None = None) -> dict[str, object]:
    status = smtp_status()
    with SessionLocal() as db:
        pending = len(due_schedules(db))
        if not status["configured"]:
            return {
                "status": "skipped",
                "reason": "smtp_not_configured",
                "pending": pending,
            }
        results = process_due(db, limit=limit)
    failed = [item for item in results if item["status"] == "failed"]
    return {
        "status": "failed" if failed else "ok",
        "processed": len(results),
        "sent": len([item for item in results if item["status"] == "sent"]),
        "failed": len(failed),
        "results": results,
    }
