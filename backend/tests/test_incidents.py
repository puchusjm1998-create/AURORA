"""Warehouse incidents: reporting, lifecycle, RBAC and audit."""

from __future__ import annotations

from tests.conftest import create_structure


def _create(admin_client, structure, **overrides):
    payload = {
        "title": "Palé dañado en el pasillo P01",
        "description": "La esquina del palé está rota y dos cajas tienen golpes.",
        "incident_type": "damage",
        "severity": "high",
        "location_id": structure["location_id"],
        "product_id": structure["product_id"],
    }
    payload.update(overrides)
    return admin_client.post("/api/v1/incidents", json=payload)


def test_incident_lifecycle_and_permissions(admin_client, worker_client, auditor_client):
    structure = create_structure(admin_client)

    created = _create(admin_client, structure)
    assert created.status_code == 201, created.text
    incident = created.json()
    assert incident["code"].startswith("AUR-INC-")
    assert incident["status"] == "open"
    assert incident["incident_type"] == "damage"
    assert incident["severity"] == "high"
    assert incident["product_id"] == structure["product_id"]
    assert incident["location_code"].startswith("ALM-")
    assert incident["reported_by_name"]
    detail = admin_client.get(f"/api/v1/incidents/{incident['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == incident["id"]

    opened = admin_client.get("/api/v1/incidents?status=open&severity=high")
    assert opened.status_code == 200
    assert opened.json()["total"] == 1

    # El trabajador puede reportar y consultar, pero no resolver.
    reported = worker_client.post(
        "/api/v1/incidents",
        json={
            "title": "Caja sin etiqueta en el muelle",
            "incident_type": "quality",
            "severity": "medium",
            "description": "Falta la etiqueta QR de trazabilidad.",
        },
    )
    assert reported.status_code == 201, reported.text
    assert worker_client.get("/api/v1/incidents").status_code == 200
    forbidden = worker_client.post(f"/api/v1/incidents/{incident['id']}/acknowledge")
    assert forbidden.status_code == 403
    assert worker_client.post(
        "/api/v1/incidents",
        json={"title": "Otra", "assigned_to": "no-existe"},
    ).status_code in (403, 404)

    # El auditor solo lee.
    assert auditor_client.get("/api/v1/incidents").status_code == 200
    assert auditor_client.post(
        "/api/v1/incidents", json={"title": "No permitido"}
    ).status_code == 403

    acknowledged = admin_client.post(f"/api/v1/incidents/{incident['id']}/acknowledge")
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "acknowledged"
    again = admin_client.post(f"/api/v1/incidents/{incident['id']}/acknowledge")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_transition"

    bad_close = admin_client.post(f"/api/v1/incidents/{incident['id']}/close")
    assert bad_close.status_code == 409

    short = admin_client.post(
        f"/api/v1/incidents/{incident['id']}/resolve", json={"resolution": "ok"}
    )
    assert short.status_code == 422

    resolved = admin_client.post(
        f"/api/v1/incidents/{incident['id']}/resolve",
        json={"resolution": "Se reubicaron las cajas y se precintó un palé nuevo."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"]

    closed = admin_client.post(f"/api/v1/incidents/{incident['id']}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"

    edited = admin_client.patch(
        f"/api/v1/incidents/{incident['id']}", json={"title": "Cambio tardío"}
    )
    assert edited.status_code == 409
    assert edited.json()["error"]["code"] == "incident_closed"

    reopened = admin_client.post(f"/api/v1/incidents/{incident['id']}/reopen")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "open"
    assert reopened.json()["resolution"] == ""

    audit = admin_client.get("/api/v1/audit?action=incident.resolved")
    assert audit.status_code == 200
    assert audit.json()["total"] == 1


def test_incident_validation_and_filters(admin_client):
    structure = create_structure(admin_client)

    assert _create(admin_client, structure, product_id="no-existe").status_code == 404
    assert _create(admin_client, structure, location_id="no-existe").status_code == 404
    assert _create(admin_client, structure, pallet_id="no-existe").status_code == 404
    assert _create(admin_client, structure, severity="urgentísima").status_code == 422

    low = _create(admin_client, structure, title="Ruido en el muelle", severity="low")
    critical = _create(
        admin_client,
        structure,
        title="Derrame de líquido",
        severity="critical",
        incident_type="safety",
    )
    assert low.status_code == 201 and critical.status_code == 201

    listed = admin_client.get("/api/v1/incidents").json()
    assert [item["severity"] for item in listed["items"][:2]] == ["critical", "low"]

    filtered = admin_client.get("/api/v1/incidents?incident_type=safety").json()
    assert filtered["total"] == 1
    search = admin_client.get("/api/v1/incidents?search=derrame").json()
    assert search["total"] == 1

    updated = admin_client.patch(
        f"/api/v1/incidents/{low.json()['id']}",
        json={"assigned_to": None, "severity": "medium"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["severity"] == "medium"
