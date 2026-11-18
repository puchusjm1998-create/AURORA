"""Tarjetas NFC: emisión con token de un solo uso, fichaje y revocación."""

from __future__ import annotations

from sqlalchemy import select

from app.models import NfcCard


def _employee(admin_client, name="Nuria"):
    response = admin_client.post(
        "/api/v1/employees",
        json={
            "first_name": name,
            "last_name": "NFC",
            "department": "Almacén",
            "position": "Mozo de almacén",
            "status": "active",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _link_worker(admin_client, users, employee_id):
    response = admin_client.patch(
        f"/api/v1/users/{users['worker'].id}", json={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text


def _issue(admin_client, employee_id, label="Llavero azul"):
    response = admin_client.post(
        "/api/v1/nfc/cards", json={"employee_id": employee_id, "label": label}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_issue_tap_revoke_and_rbac(admin_client, worker_client, auditor_client, users, db):
    employee = _employee(admin_client)
    _link_worker(admin_client, users, employee["id"])

    issued = _issue(admin_client, employee["id"])
    token = issued["token"]
    assert token.startswith("AUR-NFC-")
    assert issued["token_last4"] == token[-4:]
    assert issued["status"] == "active"
    assert issued["employee_name"] == "Nuria NFC"

    stored = db.scalars(select(NfcCard)).one()
    assert stored.token_hash != token
    assert len(stored.token_hash) == 64
    assert token not in stored.token_hash

    listing = admin_client.get("/api/v1/nfc/cards")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert "token" not in listing.json()["items"][0]
    assert listing.json()["items"][0]["token_last4"] == token[-4:]

    duplicate = admin_client.post(
        "/api/v1/nfc/cards", json={"employee_id": employee["id"], "label": "Otra"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "employee_has_active_card"

    # El trabajador ficha con su propia tarjeta; el token no se expone.
    tap = worker_client.post("/api/v1/nfc/tap", json={"token": token, "action": "auto"})
    assert tap.status_code == 200, tap.text
    assert tap.json()["event_type"] == "clock_in"
    assert tap.json()["state"] == "in"
    assert tap.json()["employee"]["code"] == employee["code"]

    again = worker_client.post("/api/v1/nfc/tap", json={"token": token, "action": "clock_in"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_sequence"

    pause = worker_client.post("/api/v1/nfc/tap", json={"token": token, "action": "break_start"})
    assert pause.status_code == 200
    assert pause.json()["state"] == "break"

    auto = worker_client.post("/api/v1/nfc/tap", json={"token": token, "action": "auto"})
    assert auto.status_code == 200
    assert auto.json()["event_type"] == "break_end"
    assert auto.json()["state"] == "in"

    out = worker_client.post("/api/v1/nfc/tap", json={"token": token, "action": "auto"})
    assert out.status_code == 200
    assert out.json()["state"] == "out"

    assert admin_client.get("/api/v1/nfc/cards").json()["items"][0]["last_used_at"] is not None
    assert worker_client.get("/api/v1/nfc/cards").status_code == 403

    # Una tarjeta revocada ya no ficha.
    revoked = admin_client.post(f"/api/v1/nfc/cards/{issued['id']}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_at"] is not None
    blocked = worker_client.post("/api/v1/nfc/tap", json={"token": token})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "card_revoked"

    assert auditor_client.post("/api/v1/nfc/tap", json={"token": token}).status_code == 403
    assert admin_client.get("/api/v1/nfc/cards?status=revoked").json()["total"] == 1
    assert admin_client.delete(f"/api/v1/nfc/cards/{issued['id']}").status_code == 200


def test_unknown_card_and_foreign_card(admin_client, worker_client, users):
    employee = _employee(admin_client, "Propia")
    _link_worker(admin_client, users, employee["id"])
    other = _employee(admin_client, "Ajena")
    foreign = _issue(admin_client, other["id"])

    unknown = worker_client.post("/api/v1/nfc/tap", json={"token": "AUR-NFC-desconocido"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"

    forbidden = worker_client.post("/api/v1/nfc/tap", json={"token": foreign["token"]})
    assert forbidden.status_code == 403


def test_inactive_employee_cannot_tap(admin_client, users, worker_client):
    employee = _employee(admin_client, "Baja")
    _link_worker(admin_client, users, employee["id"])
    card = _issue(admin_client, employee["id"])
    updated = admin_client.patch(
        f"/api/v1/employees/{employee['id']}", json={"status": "inactive"}
    )
    assert updated.status_code == 200, updated.text
    response = worker_client.post("/api/v1/nfc/tap", json={"token": card["token"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "employee_inactive"
