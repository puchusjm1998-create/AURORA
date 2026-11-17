"""Programaciones de informes y envío SMTP real contra un servidor de prueba local."""

from __future__ import annotations

import socketserver
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.services.report_delivery import process_due


class _SMTPHandler(socketserver.StreamRequestHandler):
    """Servidor SMTP mínimo: acepta EHLO/MAIL/RCPT/DATA y guarda el mensaje."""

    def handle(self) -> None:
        server: "_SMTPServer" = self.server  # type: ignore[assignment]
        self.wfile.write(b"220 aurora-test ESMTP\r\n")
        buffer: list[bytes] = []
        in_data = False
        while True:
            line = self.rfile.readline()
            if not line:
                break
            upper = line.strip().upper()
            if in_data:
                if line.strip() == b".":
                    in_data = False
                    server.messages.append(b"".join(buffer))
                    buffer = []
                    self.wfile.write(b"250 2.0.0 queued\r\n")
                else:
                    buffer.append(line)
                continue
            if upper.startswith(b"EHLO"):
                self.wfile.write(b"250-aurora-test\r\n250 8BITMIME\r\n")
            elif upper.startswith(b"HELO"):
                self.wfile.write(b"250 aurora-test\r\n")
            elif upper.startswith(b"MAIL FROM"):
                self.wfile.write(b"250 2.1.0 ok\r\n")
            elif upper.startswith(b"RCPT TO"):
                server.recipients.append(line.decode("utf-8", "replace").strip())
                self.wfile.write(b"250 2.1.5 ok\r\n")
            elif upper.startswith(b"DATA"):
                in_data = True
                self.wfile.write(b"354 end with .\r\n")
            elif upper.startswith(b"RSET") or upper.startswith(b"NOOP"):
                self.wfile.write(b"250 ok\r\n")
            elif upper.startswith(b"QUIT"):
                self.wfile.write(b"221 bye\r\n")
                break
            else:
                self.wfile.write(b"250 ok\r\n")


class _SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address):  # noqa: ANN001
        super().__init__(address, _SMTPHandler)
        self.messages: list[bytes] = []
        self.recipients: list[str] = []


@pytest.fixture()
def smtp_server(monkeypatch):
    server = _SMTPServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", server.server_address[1])
    monkeypatch.setattr(settings, "smtp_from", "aurora@test.local")
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_ssl", False)
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_timeout", 5.0)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _payload(**overrides):
    payload = {
        "name": "Inventario diario de compras",
        "report_kind": "inventory",
        "report_format": "pdf",
        "frequency": "daily",
        "hour_utc": 6,
        "recipients": ["compras@example.com", "direccion@example.com"],
    }
    payload.update(overrides)
    return payload


def test_run_now_sends_a_real_email_with_pdf(admin_client, smtp_server):
    created = admin_client.post("/api/v1/report-schedules", json=_payload())
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["next_run_at"].endswith("Z")
    assert schedule["creator_name"] == "Admin Prueba"
    assert schedule["last_status"] is None

    sent = admin_client.post(f"/api/v1/report-schedules/{schedule['id']}/run")
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert sent.json()["message_id"]

    assert len(smtp_server.messages) == 1
    raw = smtp_server.messages[0]
    assert b"To: compras@example.com, direccion@example.com" in raw
    assert b"Subject: =?utf-8?q?AURORA_=C2=B7_Inventario" in raw.lower() or b"AURORA" in raw
    assert b'Content-Type: application/pdf' in raw
    assert b"aurora-inventory-" in raw
    assert smtp_server.recipients, "El servidor SMTP no recibió destinatarios"
    assert any("compras@example.com" in line for line in smtp_server.recipients), smtp_server.recipients

    detail = admin_client.get("/api/v1/report-schedules").json()
    assert detail["total"] == 1
    assert detail["items"][0]["last_status"] == "sent"
    assert detail["items"][0]["last_run_at"]

    config = admin_client.get("/api/v1/report-schedules/config").json()
    assert config["configured"] is True
    assert config["port"] == smtp_server.server_address[1]


def test_schedule_validation_permissions_and_not_configured(
    admin_client, worker_client, monkeypatch
):
    assert worker_client.get("/api/v1/report-schedules").status_code == 403
    assert worker_client.post("/api/v1/report-schedules", json=_payload()).status_code == 403

    invalid_email = admin_client.post(
        "/api/v1/report-schedules", json=_payload(recipients=["no-es-email"])
    )
    assert invalid_email.status_code == 422

    weekly = admin_client.post(
        "/api/v1/report-schedules",
        json=_payload(frequency="weekly", weekday=None),
    )
    assert weekly.status_code == 422
    assert "weekday" in weekly.text

    created = admin_client.post(
        "/api/v1/report-schedules",
        json=_payload(frequency="weekly", weekday=2, hour_utc=5),
    )
    assert created.status_code == 201, created.text

    monkeypatch.setattr(get_settings(), "smtp_host", "")
    config = admin_client.get("/api/v1/report-schedules/config").json()
    assert config["configured"] is False
    run = admin_client.post(f"/api/v1/report-schedules/{created.json()['id']}/run")
    assert run.status_code == 409
    assert run.json()["error"]["code"] == "smtp_not_configured"


def test_update_deactivate_and_delete(admin_client):
    created = admin_client.post(
        "/api/v1/report-schedules",
        json=_payload(frequency="monthly", day_of_month=15, report_format="xlsx"),
    )
    assert created.status_code == 201, created.text
    schedule = created.json()

    paused = admin_client.patch(
        f"/api/v1/report-schedules/{schedule['id']}", json={"is_active": False}
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["is_active"] is False
    assert paused.json()["next_run_at"] is None

    resumed = admin_client.patch(
        f"/api/v1/report-schedules/{schedule['id']}",
        json={"is_active": True, "name": "Inventario mensual", "hour_utc": 4},
    )
    assert resumed.status_code == 200
    assert resumed.json()["is_active"] is True
    assert resumed.json()["name"] == "Inventario mensual"
    assert resumed.json()["next_run_at"] is not None

    invalid = admin_client.patch(
        f"/api/v1/report-schedules/{schedule['id']}", json={"frequency": "weekly"}
    )
    assert invalid.status_code == 422

    deleted = admin_client.delete(f"/api/v1/report-schedules/{schedule['id']}")
    assert deleted.status_code == 204
    assert admin_client.get("/api/v1/report-schedules").json()["total"] == 0


def test_process_due_sends_and_advances_without_stopping_on_failures(
    admin_client, db, smtp_server
):
    from app.models import ReportSchedule

    created = admin_client.post(
        "/api/v1/report-schedules",
        json=_payload(name="Programado vencido", frequency="daily", hour_utc=6),
    )
    assert created.status_code == 201, created.text
    schedule = db.get(ReportSchedule, created.json()["id"])
    now = datetime.now(timezone.utc)
    schedule.next_run_at = now - timedelta(hours=1)
    db.commit()

    results = process_due(db, now=now)
    assert len(results) == 1
    assert results[0]["status"] == "sent"
    assert len(smtp_server.messages) == 1
    db.refresh(schedule)
    assert schedule.last_status.value == "sent"
    assert schedule.next_run_at.replace(tzinfo=timezone.utc) > now

    # Un fallo de SMTP no impide procesar ni deja la programación bloqueada.
    settings = get_settings()
    settings_backup = (settings.smtp_host, settings.smtp_port)
    settings.smtp_host, settings.smtp_port = "127.0.0.1", 9
    try:
        schedule.next_run_at = now - timedelta(minutes=5)
        db.commit()
        results = process_due(db, now=now)
    finally:
        settings.smtp_host, settings.smtp_port = settings_backup

    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert "SMTP" in results[0]["detail"]
    db.refresh(schedule)
    assert schedule.last_status.value == "failed"
    assert schedule.last_error
    assert schedule.next_run_at.replace(tzinfo=timezone.utc) > now
