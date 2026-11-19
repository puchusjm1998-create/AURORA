"""Fase 8: GPS append-only y firma de entrega verificable."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from tests.conftest import create_structure


def _png_signature() -> bytes:
    image = Image.new("RGB", (320, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.line((15, 100, 80, 40, 150, 110, 220, 35, 300, 95), fill="black", width=4)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _employee(admin_client, name="Conductor"):
    response = admin_client.post(
        "/api/v1/employees",
        json={
            "first_name": name,
            "last_name": "Prueba",
            "department": "Reparto",
            "position": "Conductor",
            "status": "active",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _sealed_pallet(admin_client, structure):
    pallet = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"], "location_id": structure["location_id"]},
    )
    assert pallet.status_code == 201, pallet.text
    pallet_id = pallet.json()["id"]
    added = admin_client.post(
        f"/api/v1/pallets/{pallet_id}/items",
        json={"product_id": structure["product_id"], "quantity": "10"},
    )
    assert added.status_code == 200, added.text
    sealed = admin_client.post(f"/api/v1/pallets/{pallet_id}/seal")
    assert sealed.status_code == 200, sealed.text
    return sealed.json()


def _transit_delivery(admin_client, structure, driver_id=None, destination="Cliente GPS S.A."):
    pallet = _sealed_pallet(admin_client, structure)
    delivery = admin_client.post(
        "/api/v1/deliveries",
        json={
            "destination_name": destination,
            "destination_address": "Calle Mayor 1, Cartagena",
            "driver_employee_id": driver_id,
        },
    )
    assert delivery.status_code == 201, delivery.text
    delivery_id = delivery.json()["id"]
    assert (
        admin_client.post(
            f"/api/v1/deliveries/{delivery_id}/pallets", json={"pallet_id": pallet["id"]}
        ).status_code
        == 201
    )
    assert admin_client.post(f"/api/v1/deliveries/{delivery_id}/prepare").status_code == 200
    assert admin_client.post(f"/api/v1/deliveries/{delivery_id}/ready").status_code == 200
    assert admin_client.post(f"/api/v1/deliveries/{delivery_id}/load").status_code == 200
    assert admin_client.post(f"/api/v1/deliveries/{delivery_id}/dispatch").status_code == 200
    return delivery.json()


def _link_worker(admin_client, users, employee_id):
    response = admin_client.patch(
        f"/api/v1/users/{users['worker'].id}", json={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text


def test_driver_tracks_signs_and_delivers(admin_client, worker_client, auditor_client, users, db):
    structure = create_structure(admin_client)
    driver = _employee(admin_client)
    _link_worker(admin_client, users, driver["id"])
    delivery = _transit_delivery(admin_client, structure, driver["id"])

    assert worker_client.get("/api/v1/deliveries").status_code == 403
    mine = worker_client.get("/api/v1/deliveries/mine")
    assert mine.status_code == 200, mine.text
    assert mine.json()["total"] == 1
    assert mine.json()["items"][0]["id"] == delivery["id"]
    assert mine.json()["items"][0]["has_signature"] is False

    first = worker_client.post(
        f"/api/v1/deliveries/{delivery['id']}/tracking",
        json={"latitude": 37.605, "longitude": -0.991, "accuracy_m": 6.5, "speed_mps": 8.2},
    )
    assert first.status_code == 201, first.text
    assert first.json()["source"] == "browser"
    second = worker_client.post(
        f"/api/v1/deliveries/{delivery['id']}/tracking",
        json={"latitude": 37.606, "longitude": -0.990, "accuracy_m": 7.0},
    )
    assert second.status_code == 201, second.text

    summary = worker_client.get(f"/api/v1/deliveries/{delivery['id']}/tracking")
    assert summary.status_code == 200, summary.text
    data = summary.json()
    assert len(data["points"]) == 2
    assert data["distance_m"] > 100
    assert data["last"]["id"] == second.json()["id"]
    assert data["stale"] is False
    assert data["points"][0]["recorded_by"] == "Operario Prueba"
    assert auditor_client.get(f"/api/v1/deliveries/{delivery['id']}/tracking").status_code == 200

    latest = admin_client.get(f"/api/v1/deliveries/{delivery['id']}/tracking/latest")
    assert latest.status_code == 200
    assert latest.json()["latitude"] == 37.606

    png = _png_signature()
    signed = worker_client.post(
        f"/api/v1/deliveries/{delivery['id']}/signature",
        data={
            "signer_name": "Cliente Receptor",
            "signer_document": "12345678Z",
            "mark_delivered": "true",
            "latitude": "37.6065",
            "longitude": "-0.9895",
        },
        files={"file": ("firma.png", png, "image/png")},
    )
    assert signed.status_code == 201, signed.text
    payload = signed.json()
    assert payload["signer_name"] == "Cliente Receptor"
    assert payload["integrity"] == "ok"
    assert payload["size_bytes"] == len(png)
    assert len(payload["sha256"]) == 64
    assert payload["image_url"].endswith("/signature/image")

    delivery_after = admin_client.get(f"/api/v1/deliveries/{delivery['id']}")
    assert delivery_after.status_code == 200
    assert delivery_after.json()["status"] == "delivered"
    assert delivery_after.json()["has_signature"] is True
    assert delivery_after.json()["delivered_at"] is not None

    metadata = auditor_client.get(f"/api/v1/deliveries/{delivery['id']}/signature")
    assert metadata.status_code == 200
    assert metadata.json()["integrity"] == "ok"
    image = admin_client.get(f"/api/v1/deliveries/{delivery['id']}/signature/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == png
    assert image.headers["x-content-sha256"] == payload["sha256"]

    again = worker_client.post(
        f"/api/v1/deliveries/{delivery['id']}/signature",
        data={"signer_name": "Otro", "mark_delivered": "true"},
        files={"file": ("firma.png", png, "image/png")},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] in {"delivery_already_signed", "delivery_not_in_transit"}

    after_delivery = worker_client.post(
        f"/api/v1/deliveries/{delivery['id']}/tracking",
        json={"latitude": 37.607, "longitude": -0.989},
    )
    assert after_delivery.status_code == 409
    assert after_delivery.json()["error"]["code"] == "delivery_not_in_transit"

    audit = admin_client.get("/api/v1/audit?action=delivery.signed")
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["after"]["signer_name"] == "Cliente Receptor"


def test_tracking_validation_foreign_access_and_signature_format(
    admin_client, worker_client, users
):
    structure = create_structure(admin_client)
    driver = _employee(admin_client, "Propio")
    other_driver = _employee(admin_client, "Ajeno")
    _link_worker(admin_client, users, driver["id"])
    own = _transit_delivery(admin_client, structure, driver["id"], "Propio destino")
    foreign = _transit_delivery(admin_client, structure, other_driver["id"], "Ajeno destino")

    invalid = worker_client.post(
        f"/api/v1/deliveries/{own['id']}/tracking",
        json={"latitude": 91, "longitude": -0.99},
    )
    assert invalid.status_code == 422

    forbidden = worker_client.post(
        f"/api/v1/deliveries/{foreign['id']}/tracking",
        json={"latitude": 37.6, "longitude": -0.99},
    )
    assert forbidden.status_code == 403
    assert worker_client.get(f"/api/v1/deliveries/{foreign['id']}/tracking").status_code == 403

    png = _png_signature()
    not_png = worker_client.post(
        f"/api/v1/deliveries/{own['id']}/signature",
        data={"signer_name": "Cliente", "mark_delivered": "true"},
        files={"file": ("firma.png", b"no es un png", "image/png")},
    )
    assert not_png.status_code == 422
    assert not_png.json()["error"]["code"] == "invalid_signature_file"
    assert (
        admin_client.get(f"/api/v1/deliveries/{own['id']}").json()["has_signature"] is False
    )

    half_location = worker_client.post(
        f"/api/v1/deliveries/{own['id']}/signature",
        data={"signer_name": "Cliente", "mark_delivered": "false", "latitude": "37.6"},
        files={"file": ("firma.png", png, "image/png")},
    )
    assert half_location.status_code == 422
    assert half_location.json()["error"]["code"] == "invalid_location"

    keep_open = worker_client.post(
        f"/api/v1/deliveries/{own['id']}/signature",
        data={"signer_name": "Cliente", "mark_delivered": "false"},
        files={"file": ("firma.png", png, "image/png")},
    )
    assert keep_open.status_code == 201, keep_open.text
    still_transit = admin_client.get(f"/api/v1/deliveries/{own['id']}").json()
    assert still_transit["status"] == "in_transit"
    assert still_transit["has_signature"] is True

    # Un salto imposible no se suma a la distancia, pero el punto queda registrado.
    worker_client.post(
        f"/api/v1/deliveries/{own['id']}/tracking",
        json={"latitude": 37.60, "longitude": -0.99, "accuracy_m": 5},
    )
    worker_client.post(
        f"/api/v1/deliveries/{own['id']}/tracking",
        json={"latitude": 40.40, "longitude": -3.70, "accuracy_m": 5},
    )
    jump = worker_client.get(f"/api/v1/deliveries/{own['id']}/tracking").json()
    assert len(jump["points"]) == 2
    assert jump["distance_m"] == 0
