"""Vehicles and deliveries with real stock effects on loading."""

from __future__ import annotations

from tests.conftest import create_structure


def _sealed_pallet(admin_client, structure, quantity="20"):
    pallet = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"], "location_id": structure["location_id"]},
    )
    assert pallet.status_code == 201, pallet.text
    pallet_id = pallet.json()["id"]
    added = admin_client.post(
        f"/api/v1/pallets/{pallet_id}/items",
        json={"product_id": structure["product_id"], "quantity": quantity},
    )
    assert added.status_code == 200, added.text
    sealed = admin_client.post(f"/api/v1/pallets/{pallet_id}/seal")
    assert sealed.status_code == 200, sealed.text
    return sealed.json()


def _create_delivery(admin_client, *, vehicle_id=None, destination="Cliente Demo S.A."):
    response = admin_client.post(
        "/api/v1/deliveries",
        json={
            "destination_name": destination,
            "destination_address": "Calle Mayor 1, Cartagena",
            "vehicle_id": vehicle_id,
            "planned_departure": "2030-05-01T08:00:00Z",
            "notes": "Llamar antes de descargar",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_delivery_lifecycle_moves_stock_once(admin_client, worker_client):
    structure = create_structure(admin_client)
    pallet = _sealed_pallet(admin_client, structure, "20")

    vehicle = admin_client.post(
        "/api/v1/vehicles",
        json={"plate": "1234 abc", "model": "Iveco Daily", "capacity_kg": "3500"},
    )
    assert vehicle.status_code == 201, vehicle.text
    assert vehicle.json()["plate"] == "1234 ABC"
    vehicle_id = vehicle.json()["id"]

    duplicate = admin_client.post("/api/v1/vehicles", json={"plate": "1234 ABC"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_plate"

    delivery = _create_delivery(admin_client, vehicle_id=vehicle_id)
    assert delivery["reference"].startswith("AUR-DEL-")
    assert delivery["status"] == "draft"
    assert delivery["vehicle_plate"] == "1234 ABC"
    assert delivery["pallets"] == []

    locked = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/ready")
    assert locked.status_code == 409

    added = admin_client.post(
        f"/api/v1/deliveries/{delivery['id']}/pallets", json={"pallet_id": pallet["id"]}
    )
    assert added.status_code == 201, added.text
    assert added.json()["pallets"][0]["pallet_code"] == pallet["code"]
    assert float(added.json()["total_units"]) == 20

    prepared = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/prepare")
    assert prepared.status_code == 200
    assert prepared.json()["status"] == "preparing"
    ready = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    product_before = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product_before["stock"]["on_hand"]) == 20

    loaded = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/load")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["status"] == "loaded"
    product_after = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product_after["stock"]["on_hand"]) == 0
    pallet_after = admin_client.get(f"/api/v1/pallets/{pallet['id']}").json()
    assert pallet_after["status"] == "in_transit"

    cannot_cancel = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/cancel")
    assert cannot_cancel.status_code == 409

    dispatched = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/dispatch")
    assert dispatched.status_code == 200
    assert dispatched.json()["status"] == "in_transit"
    assert dispatched.json()["departed_at"]

    delivered = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/deliver")
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "delivered"
    assert delivered.json()["delivered_at"]
    assert (
        admin_client.get(f"/api/v1/pallets/{pallet['id']}").json()["status"] == "shipped"
    )

    audit = admin_client.get("/api/v1/audit?action=delivery.loaded")
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["after"]["movements"] == 1

    assert (
        worker_client.post(
            "/api/v1/deliveries", json={"destination_name": "No permitido"}
        ).status_code
        == 403
    )
    assert worker_client.get("/api/v1/deliveries").status_code == 403


def test_delivery_validations_and_cancel_releases_pallets(admin_client):
    structure = create_structure(admin_client)
    pallet = _sealed_pallet(admin_client, structure, "5")
    open_pallet = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"], "location_id": structure["location_id"]},
    ).json()

    delivery = _create_delivery(admin_client)
    not_sealed = admin_client.post(
        f"/api/v1/deliveries/{delivery['id']}/pallets", json={"pallet_id": open_pallet["id"]}
    )
    assert not_sealed.status_code == 409
    assert not_sealed.json()["error"]["code"] == "pallet_not_sealed"

    assert (
        admin_client.post(
            f"/api/v1/deliveries/{delivery['id']}/pallets", json={"pallet_id": pallet["id"]}
        ).status_code
        == 201
    )
    assert (
        admin_client.post(
            f"/api/v1/deliveries/{delivery['id']}/pallets", json={"pallet_id": pallet["id"]}
        ).status_code
        == 409
    )

    other = _create_delivery(admin_client, destination="Otro cliente")
    busy = admin_client.post(
        f"/api/v1/deliveries/{other['id']}/pallets", json={"pallet_id": pallet["id"]}
    )
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "pallet_in_delivery"

    prepared = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/prepare").json()
    assert prepared["status"] == "preparing"
    assert (
        admin_client.patch(
            f"/api/v1/deliveries/{delivery['id']}", json={"notes": "Cambio"}
        ).status_code
        == 200
    )

    cancelled = admin_client.post(f"/api/v1/deliveries/{delivery['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["pallets"] == []

    # El palé vuelve a estar disponible para otro reparto activo.
    reused = admin_client.post(
        f"/api/v1/deliveries/{other['id']}/pallets", json={"pallet_id": pallet["id"]}
    )
    assert reused.status_code == 201, reused.text

    removed = admin_client.delete(
        f"/api/v1/deliveries/{other['id']}/pallets/{pallet['id']}"
    )
    assert removed.status_code == 200
    assert removed.json()["pallets"] == []

    # No se puede cargar un reparto sin palés.
    admin_client.post(f"/api/v1/deliveries/{other['id']}/prepare")
    empty_ready = admin_client.post(f"/api/v1/deliveries/{other['id']}/ready")
    assert empty_ready.status_code == 422

    draft = _create_delivery(admin_client, destination="Borrador")
    deleted = admin_client.delete(f"/api/v1/deliveries/{draft['id']}")
    assert deleted.status_code == 200
    assert admin_client.get(f"/api/v1/deliveries/{draft['id']}").status_code == 404

    listing = admin_client.get("/api/v1/deliveries?status=cancelled")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
