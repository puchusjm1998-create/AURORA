"""Reglas de alerta, evaluación, reconocimiento y notificación."""

from __future__ import annotations

import pytest

from app.core.config import get_settings


def _rule_payload(**overrides):
    payload = {
        "name": "Tareas abiertas bajo control",
        "metric": "open_tasks",
        "operator": "gte",
        "threshold": "0",
        "severity": "warning",
        "cooldown_minutes": 0,
        "notify_emails": [],
    }
    payload.update(overrides)
    return payload


def test_rule_lifecycle_and_evaluation(admin_client, worker_client):
    assert worker_client.get("/api/v1/alerts/rules").status_code == 200
    assert worker_client.post("/api/v1/alerts/rules", json=_rule_payload()).status_code == 403

    created = admin_client.post("/api/v1/alerts/rules", json=_rule_payload())
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["creator_name"] == "Admin Prueba"
    assert rule["metric"] == "open_tasks"

    metrics = admin_client.get("/api/v1/alerts/metrics").json()
    assert len(metrics) == 7
    assert {item["metric"] for item in metrics} >= {"open_tasks", "stock_units"}

    first = admin_client.post("/api/v1/alerts/evaluate")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["evaluated"] == 1
    assert body["triggered"] == 1
    alert = body["alerts"][0]
    assert alert["status"] == "open"
    assert alert["severity"] == "warning"
    assert alert["message"].startswith("Tareas abiertas bajo control")
    assert alert["rule_name"] == "Tareas abiertas bajo control"

    second = admin_client.post("/api/v1/alerts/evaluate").json()
    assert second["triggered"] == 0
    assert second["skipped"] == 1

    listed = admin_client.get("/api/v1/alerts", params={"status": "open"}).json()
    assert listed["total"] == 1

    assert worker_client.post(f"/api/v1/alerts/{alert['id']}/acknowledge").status_code == 403
    acked = admin_client.post(
        f"/api/v1/alerts/{alert['id']}/acknowledge", json={"note": "Revisado por logística"}
    )
    assert acked.status_code == 200, acked.text
    assert acked.json()["status"] == "acknowledged"
    assert acked.json()["acknowledger_name"] == "Admin Prueba"
    assert acked.json()["note"] == "Revisado por logística"

    assert admin_client.post(f"/api/v1/alerts/{alert['id']}/acknowledge").status_code == 409

    resolved = admin_client.post(
        f"/api/v1/alerts/{alert['id']}/resolve", json={"note": "Tareas reasignadas"}
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolver_name"] == "Admin Prueba"

    # Cooldown 0 y alerta resuelta: la condición sigue siendo cierta y vuelve a alertar.
    third = admin_client.post("/api/v1/alerts/evaluate").json()
    assert third["triggered"] == 1
    assert third["alerts"][0]["id"] != alert["id"]

    # La regla con alertas no se puede borrar; se desactiva.
    blocked = admin_client.delete(f"/api/v1/alerts/rules/{rule['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "rule_has_alerts"

    paused = admin_client.patch(
        f"/api/v1/alerts/rules/{rule['id']}", json={"is_active": False}
    )
    assert paused.status_code == 200
    assert paused.json()["is_active"] is False
    assert admin_client.post("/api/v1/alerts/evaluate").json()["evaluated"] == 0


def test_rule_validation_and_delete_without_alerts(admin_client):
    invalid_email = admin_client.post(
        "/api/v1/alerts/rules", json=_rule_payload(notify_emails=["no-es-correo"])
    )
    assert invalid_email.status_code == 422

    invalid_operator = admin_client.post(
        "/api/v1/alerts/rules", json=_rule_payload(operator="distinto")
    )
    assert invalid_operator.status_code == 422

    created = admin_client.post("/api/v1/alerts/rules", json=_rule_payload(name="Temporal"))
    assert created.status_code == 201
    deleted = admin_client.delete(f"/api/v1/alerts/rules/{created.json()['id']}")
    assert deleted.status_code == 204
    assert admin_client.get("/api/v1/alerts/rules").json()["total"] == 0


def test_notification_uses_smtp_and_records_errors(admin_client, monkeypatch):
    captured = []

    def fake_send(message):
        captured.append(message)
        return "<alerta@test>"

    monkeypatch.setattr("app.services.alerts.send_mail", fake_send)
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.test.local")

    created = admin_client.post(
        "/api/v1/alerts/rules",
        json=_rule_payload(name="Aviso a operaciones", notify_emails=["ops@example.com"]),
    )
    assert created.status_code == 201
    result = admin_client.post("/api/v1/alerts/evaluate").json()
    alert = result["alerts"][0]
    assert alert["notified_at"] is not None
    assert len(captured) == 1
    assert captured[0].to == ["ops@example.com"]
    assert "AURORA" in captured[0].subject
    assert "tareas abiertas" in captured[0].body

    # Sin SMTP configurado la alerta se crea igualmente y deja el motivo visible.
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    admin_client.post(f"/api/v1/alerts/{alert['id']}/resolve")
    second = admin_client.post(
        "/api/v1/alerts/rules",
        json=_rule_payload(
            name="Aviso sin correo", metric="open_incidents", notify_emails=["ops@example.com"]
        ),
    )
    assert second.status_code == 201
    evaluated = admin_client.post("/api/v1/alerts/evaluate").json()
    pending = next(item for item in evaluated["alerts"] if item["rule_name"] == "Aviso sin correo")
    assert pending["notified_at"] is None
    assert "SMTP" in pending["notification_error"]


def test_cooldown_blocks_repeated_alerts(admin_client):
    created = admin_client.post(
        "/api/v1/alerts/rules", json=_rule_payload(name="Con cooldown", cooldown_minutes=60)
    )
    assert created.status_code == 201
    assert admin_client.post("/api/v1/alerts/evaluate").json()["triggered"] == 1
    alert_id = admin_client.get("/api/v1/alerts").json()["items"][0]["id"]
    admin_client.post(f"/api/v1/alerts/{alert_id}/resolve")
    again = admin_client.post("/api/v1/alerts/evaluate").json()
    assert again["triggered"] == 0
    assert again["skipped"] == 1
