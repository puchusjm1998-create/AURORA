"""Slotting and picking-route suggestions."""

from __future__ import annotations

from tests.conftest import create_structure


def _location(admin_client, warehouse_id, aisle, position, *, pick_face=False, capacity=2):
    response = admin_client.post(
        "/api/v1/locations",
        json={
            "warehouse_id": warehouse_id,
            "aisle": aisle,
            "rack": "EA",
            "level": "N01",
            "position": position,
            "capacity_pallets": capacity,
            "is_pick_face": pick_face,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _receive(admin_client, structure, quantity, location_id=None):
    response = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "reception",
            "product_id": structure["product_id"],
            "quantity": quantity,
            "to_location_id": location_id or structure["location_id"],
            "reason": "Recepción de prueba",
            "confirm": True,
            "physical_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ship(admin_client, structure, quantity, location_id=None):
    response = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "shipment",
            "product_id": structure["product_id"],
            "quantity": quantity,
            "from_location_id": location_id or structure["location_id"],
            "reason": "Salida de prueba",
            "confirm": True,
            "physical_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_putaway_suggestion_ranks_consolidation(admin_client):
    structure = create_structure(admin_client)
    _location(admin_client, structure["warehouse_id"], "P01", "POS01", pick_face=True)
    _receive(admin_client, structure, "5")

    response = admin_client.get(
        f"/api/v1/optimization/putaway?product_id={structure['product_id']}&pallets=1"
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pallets"] == 1
    assert data["fits"] is True
    assert data["candidates"]
    assert data["candidates"][0]["location_id"] == structure["location_id"]
    assert any("consolida" in reason.lower() for reason in data["candidates"][0]["reasons"])
    assert float(data["candidates"][0]["same_product_units"]) == 5
    assert 0 <= data["candidates"][0]["score"] <= 100
    assert data["assumptions"]["aisle_pitch_m"] == 3.0

    huge = admin_client.get(
        f"/api/v1/optimization/putaway?product_id={structure['product_id']}&pallets=50"
    )
    assert huge.status_code == 200
    assert huge.json()["fits"] is False
    assert all(candidate["free_pallets"] < 50 for candidate in huge.json()["candidates"])

    missing = admin_client.get("/api/v1/optimization/putaway?product_id=no-existe")
    assert missing.status_code == 404


def test_picking_route_is_serpentine_and_measured(admin_client):
    structure = create_structure(admin_client)
    p01_a = _location(admin_client, structure["warehouse_id"], "P01", "POS01")
    p01_b = _location(admin_client, structure["warehouse_id"], "P01", "POS05")
    p02 = _location(admin_client, structure["warehouse_id"], "P02", "POS02")

    response = admin_client.post(
        "/api/v1/optimization/picking-route",
        json={
            "location_ids": [p02["id"], p01_b["id"], p01_a["id"], p01_a["id"]],
            "return_to_dispatch": True,
        },
    )
    assert response.status_code == 200, response.text
    route = response.json()
    codes = [stop["location_code"] for stop in route["stops"]]
    assert codes == [p01_a["full_code"], p01_b["full_code"], p02["full_code"]]
    assert route["stops"][0]["distance_from_previous_m"] == 0.0
    assert route["total_distance_m"] == 14.0
    assert route["total_pick_seconds"] == 75

    without_return = admin_client.post(
        "/api/v1/optimization/picking-route",
        json={"location_ids": [p02["id"], p01_b["id"], p01_a["id"]], "return_to_dispatch": False},
    )
    assert without_return.status_code == 200
    assert without_return.json()["total_distance_m"] == 10.0

    invalid = admin_client.post("/api/v1/optimization/picking-route", json={})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "route_source_required"

    both = admin_client.post(
        "/api/v1/optimization/picking-route",
        json={"location_ids": [p01_a["id"]], "reservation_reference": "PED"},
    )
    assert both.status_code == 422


def test_route_from_active_reservation(admin_client, worker_client):
    structure = create_structure(admin_client)
    _receive(admin_client, structure, "10")
    reserved = admin_client.post(
        "/api/v1/reservations",
        json={
            "product_id": structure["product_id"],
            "location_id": structure["location_id"],
            "quantity": "3",
            "reference": "PED-RUTA-1",
        },
    )
    assert reserved.status_code == 201, reserved.text

    route = worker_client.post(
        "/api/v1/optimization/picking-route",
        json={"reservation_reference": "PED-RUTA-1"},
    )
    assert route.status_code == 200, route.text
    data = route.json()
    assert len(data["stops"]) == 1
    assert data["stops"][0]["product_sku"] == structure["sku"]
    assert float(data["stops"][0]["quantity"]) == 3
    assert data["total_distance_m"] > 0

    missing = admin_client.post(
        "/api/v1/optimization/picking-route",
        json={"reservation_reference": "PED-INEXISTENTE"},
    )
    assert missing.status_code == 404


def test_slotting_flags_fast_mover_outside_pick_face(admin_client):
    structure = create_structure(admin_client)
    _receive(admin_client, structure, "10")
    for _ in range(3):
        _ship(admin_client, structure, "1")

    response = admin_client.get("/api/v1/optimization/slotting?days=30")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] >= 1
    row = next(item for item in data["items"] if item["product_id"] == structure["product_id"])
    assert row["moves"] == 3
    assert float(row["units_out"]) == 3
    assert row["in_pick_face"] is False
    assert row["recommendation"] == "Mover a cara de picking"
    assert row["locations"] == 1
    assert float(row["on_hand"]) == 7

    invalid = admin_client.get("/api/v1/optimization/slotting?days=0")
    assert invalid.status_code == 422
