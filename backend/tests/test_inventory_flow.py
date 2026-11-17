"""Inventory, movement ledger and stock invariant tests."""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import create_structure


def receive(admin_client, structure, quantity="100", **extra):
    payload = {
        "movement_type": "reception",
        "product_id": structure["product_id"],
        "quantity": quantity,
        "to_location_id": structure["location_id"],
        "reason": "Recepción de prueba",
        "confirm": True,
        "physical_confirmed": True,
        **extra,
    }
    return admin_client.post("/api/v1/movements", json=payload)


def test_complete_reception_location_and_expedition(admin_client):
    structure = create_structure(admin_client)
    product_url = f"/api/v1/products/{structure['product_id']}"

    response = receive(admin_client, structure, "100")
    assert response.status_code == 201, response.text
    movement = response.json()
    assert movement["status"] == "confirmed"
    assert movement["reference"].startswith("AUR-MOV-")
    assert movement["allocations"][0]["location_code"] == structure["location_code"]

    product = admin_client.get(product_url).json()
    assert float(product["stock"]["on_hand"]) == 100
    assert float(product["stock"]["available"]) == 100
    assert product["stock"]["locations"] == 1

    whereabouts = admin_client.get(f"{product_url}/whereabouts").json()
    assert whereabouts["positions"][0]["location_code"] == structure["location_code"]
    assert float(whereabouts["positions"][0]["quantity"]) == 100

    shipment = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "shipment",
            "product_id": structure["product_id"],
            "quantity": "30",
            "from_location_id": structure["location_id"],
            "reason": "Pedido cliente",
            "confirm": True,
        },
    )
    assert shipment.status_code == 201, shipment.text
    product = admin_client.get(product_url).json()
    assert float(product["stock"]["on_hand"]) == 70

    history = admin_client.get("/api/v1/movements").json()
    assert history["total"] == 2
    assert history["items"][0]["movement_type"] == "shipment"


def test_stock_cannot_go_negative(admin_client):
    structure = create_structure(admin_client)
    assert receive(admin_client, structure, "10").status_code == 201

    response = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "shipment",
            "product_id": structure["product_id"],
            "quantity": "25",
            "from_location_id": structure["location_id"],
            "confirm": True,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_stock"

    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 10


def test_idempotency_key_prevents_duplicate_movements(admin_client):
    structure = create_structure(admin_client)
    key = str(uuid.uuid4())
    first = receive(admin_client, structure, "15", idempotency_key=key)
    second = receive(admin_client, structure, "15", idempotency_key=key)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["reference"] == second.json()["reference"]

    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 15
    history = admin_client.get("/api/v1/movements").json()
    assert history["total"] == 1

    mismatched = receive(admin_client, structure, "99", idempotency_key=key)
    assert mismatched.status_code == 409
    assert mismatched.json()["error"]["code"] == "idempotency_mismatch"


def test_draft_movement_does_not_change_stock_until_confirmed(admin_client):
    structure = create_structure(admin_client)
    draft = receive(admin_client, structure, "40", confirm=False)
    assert draft.status_code == 201
    movement = draft.json()
    assert movement["status"] == "draft"

    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 0

    confirmed = admin_client.post(f"/api/v1/movements/{movement['id']}/confirm", json={})
    assert confirmed.status_code == 200
    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 40

    duplicate = admin_client.post(f"/api/v1/movements/{movement['id']}/confirm", json={})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "already_confirmed"

    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 40


def test_cancelled_draft_cannot_be_confirmed(admin_client):
    structure = create_structure(admin_client)
    draft = receive(admin_client, structure, "5", confirm=False).json()
    cancelled = admin_client.post(
        f"/api/v1/movements/{draft['id']}/cancel", json={"reason": "Error de captura"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert admin_client.post(f"/api/v1/movements/{draft['id']}/confirm", json={}).status_code == 409


def test_reservation_reduces_available_stock(admin_client):
    structure = create_structure(admin_client)
    assert receive(admin_client, structure, "100").status_code == 201

    reservation = admin_client.post(
        "/api/v1/reservations",
        json={
            "product_id": structure["product_id"],
            "location_id": structure["location_id"],
            "quantity": "30",
            "reference": "PEDIDO-777",
        },
    )
    assert reservation.status_code == 201, reservation.text
    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["reserved"]) == 30
    assert float(product["stock"]["available"]) == 70

    too_much = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "shipment",
            "product_id": structure["product_id"],
            "quantity": "80",
            "from_location_id": structure["location_id"],
            "confirm": True,
        },
    )
    assert too_much.status_code == 422

    released = admin_client.post(
        f"/api/v1/reservations/{reservation.json()['id']}/release"
    )
    assert released.status_code == 200
    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["available"]) == 100


def test_internal_move_keeps_total_stock(admin_client):
    structure = create_structure(admin_client)
    assert receive(admin_client, structure, "50").status_code == 201
    second = admin_client.post(
        "/api/v1/locations",
        json={
            "warehouse_id": structure["warehouse_id"],
            "aisle": "P05",
            "rack": "EA",
            "level": "N01",
            "position": "POS01",
        },
    ).json()

    moved = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "internal_move",
            "product_id": structure["product_id"],
            "quantity": "20",
            "from_location_id": structure["location_id"],
            "to_location_id": second["id"],
            "confirm": True,
        },
    )
    assert moved.status_code == 201, moved.text
    whereabouts = admin_client.get(
        f"/api/v1/products/{structure['product_id']}/whereabouts"
    ).json()
    assert float(whereabouts["stock"]["on_hand"]) == 50
    positions = {p["location_code"]: float(p["quantity"]) for p in whereabouts["positions"]}
    assert positions[structure["location_code"]] == 30
    assert positions[second["full_code"]] == 20


def test_adjustment_requires_authority_and_reason(admin_client, worker_client):
    structure = create_structure(admin_client)
    assert receive(admin_client, structure, "10").status_code == 201

    missing_reason = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "adjustment",
            "product_id": structure["product_id"],
            "quantity": "-2",
            "from_location_id": structure["location_id"],
            "confirm": True,
        },
    )
    assert missing_reason.status_code == 422

    allowed = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "adjustment",
            "product_id": structure["product_id"],
            "quantity": "-2",
            "from_location_id": structure["location_id"],
            "reason": "Rotura detectada en inventario",
            "confirm": True,
        },
    )
    assert allowed.status_code == 201, allowed.text
    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 8

    forbidden = worker_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "adjustment",
            "product_id": structure["product_id"],
            "quantity": "1",
            "to_location_id": structure["location_id"],
            "reason": "Intento no autorizado",
            "confirm": True,
        },
    )
    assert forbidden.status_code == 403


def test_batch_tracking_requires_and_tracks_batch(admin_client):
    structure = create_structure(admin_client, tracking_mode="batch")
    missing = receive(admin_client, structure, "10")
    assert missing.status_code == 422
    assert "lote" in missing.json()["error"]["message"].lower()

    ok = receive(admin_client, structure, "10", batch_code="LOTE-A")
    assert ok.status_code == 201
    db_batch = admin_client.get(
        f"/api/v1/products/{structure['product_id']}/whereabouts"
    ).json()
    assert float(db_batch["stock"]["on_hand"]) == 10


def test_unit_tracking_creates_individual_codes(admin_client):
    structure = create_structure(admin_client, tracking_mode="unit")
    response = receive(
        admin_client, structure, "2", unit_serials=["SN-001", "SN-002"]
    )
    assert response.status_code == 201, response.text

    units = admin_client.get(f"/api/v1/products/{structure['product_id']}/units").json()
    assert units["total"] == 2
    codes = [unit["code"] for unit in units["items"]]
    assert all(code.startswith("AUR-OBJ-") for code in codes)

    shipped = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "shipment",
            "product_id": structure["product_id"],
            "quantity": "1",
            "from_location_id": structure["location_id"],
            "confirm": True,
        },
    )
    assert shipped.status_code == 201
    units = admin_client.get(f"/api/v1/products/{structure['product_id']}/units").json()
    statuses = sorted(unit["status"] for unit in units["items"])
    assert statuses == ["in_stock", "shipped"]


def test_duplicate_location_code_is_rejected(admin_client):
    structure = create_structure(admin_client)
    response = admin_client.post(
        "/api/v1/locations",
        json={
            "warehouse_id": structure["warehouse_id"],
            "aisle": "P04",
            "rack": "EB",
            "level": "N02",
            "position": "POS03",
        },
    )
    assert response.status_code == 409


def test_products_can_be_searched_by_reference_and_location(admin_client):
    structure = create_structure(admin_client)
    assert receive(admin_client, structure, "5").status_code == 201
    by_location = admin_client.get(
        "/api/v1/products", params={"location_code": structure["location_code"]}
    ).json()
    assert by_location["total"] == 1
    by_sku = admin_client.get("/api/v1/products", params={"search": structure["sku"]}).json()
    assert by_sku["total"] == 1


def test_audit_log_is_append_only(admin_client, db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError

    rows = admin_client.get("/api/v1/audit").json()
    assert rows["total"] > 0
    with pytest.raises((IntegrityError, DBAPIError)):
        db.execute(text("UPDATE audit_logs SET action = 'tampered'"))
        db.commit()
    db.rollback()
    with pytest.raises((IntegrityError, DBAPIError)):
        db.execute(text("DELETE FROM audit_logs"))
        db.commit()
    db.rollback()


def test_movement_rows_cannot_be_deleted(admin_client, db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError

    structure = create_structure(admin_client)
    assert receive(admin_client, structure, "3").status_code == 201
    with pytest.raises((IntegrityError, DBAPIError)):
        db.execute(text("DELETE FROM stock_movements"))
        db.commit()
    db.rollback()
