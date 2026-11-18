"""Fase 8: registro de llamadas, handoff SIP y proveedor webhook."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.api.routes import calls as calls_route


def test_call_handoff_log_and_permissions(admin_client, auditor_client):
    status = admin_client.get("/api/v1/calls/config")
    assert status.status_code == 200, status.text
    assert status.json()["mode"] == "handoff"
    assert status.json()["can_originate"] is False
    assert "handoff" in status.json()["message"].lower()

    created = admin_client.post(
        "/api/v1/calls",
        json={
            "contact_name": "Cliente Demo",
            "phone": "+34 600 123 456",
            "purpose": "Confirmar ventana de descarga",
        },
    )
    assert created.status_code == 201, created.text
    call = created.json()
    assert call["phone"] == "+34600123456"
    assert call["status"] == "handoff"
    assert call["tel_uri"] == "tel:+34600123456"
    assert call["dial_uri"].startswith("tel:")
    assert call["authorized_by"] == "Admin Prueba"
    assert call["provider"] == "sip-handoff"

    listing = admin_client.get("/api/v1/calls")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert admin_client.get(f"/api/v1/calls/{call['id']}").status_code == 200

    closed = admin_client.patch(
        f"/api/v1/calls/{call['id']}",
        json={"status": "completed", "result": "Llamada atendida; descarga a las 10:30."},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "completed"
    assert closed.json()["ended_at"] is not None

    again = admin_client.patch(
        f"/api/v1/calls/{call['id']}", json={"status": "failed", "result": "Duplicada"}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "call_closed"

    assert auditor_client.get("/api/v1/calls").status_code == 403
    assert (
        auditor_client.post(
            "/api/v1/calls",
            json={"contact_name": "Sin permiso", "phone": "+34600000000"},
        ).status_code
        == 403
    )

    invalid_phone = admin_client.post(
        "/api/v1/calls",
        json={"contact_name": "Mal teléfono", "phone": "+34+600"},
    )
    assert invalid_phone.status_code == 422
    assert invalid_phone.json()["error"]["code"] == "invalid_phone"

    audit = admin_client.get("/api/v1/audit?action=call.created")
    assert audit.status_code == 200
    assert audit.json()["total"] == 1


def test_webhook_originates_call_and_handles_provider_errors(admin_client, monkeypatch):
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
            received.append(
                {
                    "authorization": self.headers.get("authorization"),
                    "payload": json.loads(body.decode("utf-8")),
                }
            )
            response = json.dumps({"call_id": "prov-123", "status": "queued"}).encode()
            self.send_response(202)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(calls_route.settings, "telephony_mode", "webhook")
        monkeypatch.setattr(
            calls_route.settings,
            "telephony_webhook_url",
            f"http://127.0.0.1:{server.server_port}/calls",
        )
        monkeypatch.setattr(calls_route.settings, "telephony_webhook_token", "secreto")
        monkeypatch.setattr(calls_route.settings, "telephony_sip_domain", "sip.aurora.test")

        status = admin_client.get("/api/v1/calls/config").json()
        assert status["mode"] == "webhook"
        assert status["can_originate"] is True
        assert status["sip_domain"] == "sip.aurora.test"

        created = admin_client.post(
            "/api/v1/calls",
            json={
                "contact_name": "Transportes Norte",
                "phone": "968 123 456",
                "purpose": "Reprogramar entrega",
            },
        )
        assert created.status_code == 201, created.text
        call = created.json()
        assert call["status"] == "queued"
        assert call["provider_call_id"] == "prov-123"
        assert call["provider"] == "webhook"
        assert call["sip_uri"] == "sip:968123456@sip.aurora.test"
        assert call["dial_uri"] == call["sip_uri"]

        assert len(received) == 1
        assert received[0]["authorization"] == "Bearer secreto"
        assert received[0]["payload"]["to"] == "968123456"
        assert received[0]["payload"]["contact_name"] == "Transportes Norte"

        monkeypatch.setattr(calls_route.settings, "telephony_webhook_url", "")
        unavailable = admin_client.post(
            "/api/v1/calls",
            json={"contact_name": "Sin proveedor", "phone": "968000000"},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "telephony_not_configured"
    finally:
        server.shutdown()
        server.server_close()
