"""AURORA Voice: interpretación real de consultas sobre la base de datos."""

from __future__ import annotations

from tests.conftest import create_structure


def _receive(admin_client, structure, quantity="100"):
    response = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "reception",
            "product_id": structure["product_id"],
            "quantity": quantity,
            "to_location_id": structure["location_id"],
            "reason": "Recepción para prueba de voz",
            "confirm": True,
            "physical_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text


def test_voice_status_and_product_location(admin_client):
    structure = create_structure(admin_client)
    _receive(admin_client, structure, "100")

    status = admin_client.get("/api/v1/voice/status")
    assert status.status_code == 200
    details = status.json()["details"]
    assert details["provider"] == "aurora-builtin"
    assert details["audio_leaves_device"] is False
    assert details["stt"] == "Web Speech API del navegador"
    assert "ubicación y stock de un producto" in details["capabilities"]

    response = admin_client.post(
        "/api/v1/voice/query", json={"text": "¿Dónde está el producto de prueba?"}
    )
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["intent"] == "product_location"
    assert reply["confidence"] >= 0.9
    assert structure["location_code"] in reply["answer"]
    assert "100" in reply["answer"]
    assert reply["data"]["product"]["sku"] == structure["sku"]
    assert reply["data"]["stock"]["on_hand"] == "100"
    assert reply["data"]["stock"]["positions"][0]["location_code"] == structure["location_code"]

    by_sku = admin_client.post(
        "/api/v1/voice/query", json={"text": f"stock de {structure['sku']}"}
    ).json()
    assert by_sku["intent"] == "product_location"
    assert by_sku["data"]["product"]["sku"] == structure["sku"]


def test_voice_low_stock_summary_and_unknown(admin_client):
    structure = create_structure(admin_client)
    low = admin_client.post(
        "/api/v1/products",
        json={
            "name": "Filtro bajo mínimo",
            "category": "Test",
            "uom": "ud",
            "purchase_price": "1.00",
            "unit_price": "2.00",
            "min_stock": "10",
        },
    )
    assert low.status_code == 201

    low_reply = admin_client.post(
        "/api/v1/voice/query", json={"text": "¿Qué productos están bajo mínimo?"}
    ).json()
    assert low_reply["intent"] == "low_stock"
    assert low_reply["data"]["count"] >= 1
    assert any(item["sku"] == low.json()["sku"] for item in low_reply["data"]["products"])

    summary = admin_client.post(
        "/api/v1/voice/query", json={"text": "dame un resumen del almacén"}
    ).json()
    assert summary["intent"] == "summary"
    assert "unidades en stock" in summary["answer"]
    assert "productos bajo mínimo" in summary["answer"]

    tasks = admin_client.post(
        "/api/v1/voice/query", json={"text": "¿cuántas tareas quedan abiertas?"}
    ).json()
    assert tasks["intent"] == "open_tasks"
    assert tasks["data"]["count"] == 0

    incidents = admin_client.post(
        "/api/v1/voice/query", json={"text": "¿hay incidencias abiertas?"}
    ).json()
    assert incidents["intent"] == "open_incidents"
    assert incidents["data"]["count"] == 0

    deliveries = admin_client.post(
        "/api/v1/voice/query", json={"text": "¿cuántos repartos quedan?"}
    ).json()
    assert deliveries["intent"] == "pending_deliveries"
    assert deliveries["data"]["count"] == 0

    unknown = admin_client.post(
        "/api/v1/voice/query", json={"text": "ponme música"}
    ).json()
    assert unknown["intent"] == "unknown"
    assert unknown["suggestions"]

    not_found = admin_client.post(
        "/api/v1/voice/query", json={"text": "¿dónde está el producto inexistente xyz?"}
    ).json()
    assert not_found["intent"] == "product_not_found"

    assert admin_client.post("/api/v1/voice/query", json={"text": "x"}).status_code == 422


def test_voice_respects_permissions(worker_client):
    response = worker_client.post(
        "/api/v1/voice/query", json={"text": "¿cuántas tareas hay abiertas?"}
    )
    assert response.status_code == 200
    reply = response.json()
    assert reply["intent"] == "forbidden"
    assert "no el resumen global" in reply["answer"]

    summary = worker_client.post(
        "/api/v1/voice/query", json={"text": "resumen del almacén"}
    ).json()
    assert summary["intent"] == "summary"
    assert "tareas abiertas" not in summary["answer"]
    assert "unidades en stock" in summary["answer"]
