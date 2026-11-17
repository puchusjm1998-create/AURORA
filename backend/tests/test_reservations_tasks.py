"""Stock reservations and warehouse task lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import StockReservation
from tests.conftest import create_structure


def _stock_in(admin_client, structure, quantity="10"):
    response = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "reception",
            "product_id": structure["product_id"],
            "quantity": quantity,
            "to_location_id": structure["location_id"],
            "reason": "Recepción de prueba",
            "confirm": True,
            "physical_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _link_employee(admin_client, users, email="worker@test.local"):
    employee = admin_client.post(
        "/api/v1/employees",
        json={
            "first_name": "Operario",
            "last_name": "Asignado",
            "department": "Almacén",
            "position": "Mozo de almacén",
            "status": "active",
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]
    user_id = users["worker"].id
    linked = admin_client.patch(f"/api/v1/users/{user_id}", json={"employee_id": employee_id})
    assert linked.status_code == 200, linked.text
    return employee_id


def test_reservation_lifecycle(admin_client, worker_client):
    structure = create_structure(admin_client)
    _stock_in(admin_client, structure, "10")

    created = admin_client.post(
        "/api/v1/reservations",
        json={
            "product_id": structure["product_id"],
            "location_id": structure["location_id"],
            "quantity": "4",
            "reference": "PED-2026-0001",
        },
    )
    assert created.status_code == 201, created.text
    reservation = created.json()
    assert reservation["status"] == "active"
    assert reservation["reference"] == "PED-2026-0001"
    assert reservation["location_code"].startswith("ALM-")

    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["reserved"]) == 4
    assert float(product["stock"]["available"]) == 6

    over = admin_client.post(
        "/api/v1/reservations",
        json={
            "product_id": structure["product_id"],
            "location_id": structure["location_id"],
            "quantity": "20",
            "reference": "PED-2026-0002",
        },
    )
    assert over.status_code == 422, over.text
    assert over.json()["error"]["code"] == "insufficient_stock"

    listed = admin_client.get("/api/v1/reservations?status=active")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    released = admin_client.post(f"/api/v1/reservations/{reservation['id']}/release")
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "released"
    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["reserved"]) == 0
    assert float(product["stock"]["available"]) == 10

    again = admin_client.post(f"/api/v1/reservations/{reservation['id']}/release")
    assert again.status_code == 409

    # El trabajador no puede gestionar reservas (nivel 4).
    forbidden = worker_client.post(
        "/api/v1/reservations",
        json={
            "product_id": structure["product_id"],
            "location_id": structure["location_id"],
            "quantity": "1",
            "reference": "PED-NO",
        },
    )
    assert forbidden.status_code == 403
    assert worker_client.get("/api/v1/reservations").status_code == 403


def test_expired_reservation_is_released_by_the_server(admin_client, db):
    structure = create_structure(admin_client)
    _stock_in(admin_client, structure, "10")

    created = admin_client.post(
        "/api/v1/reservations",
        json={
            "product_id": structure["product_id"],
            "location_id": structure["location_id"],
            "quantity": "5",
            "reference": "PED-2026-CADUCA",
            "expires_at": "2030-01-01T10:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    reservation_id = created.json()["id"]
    assert created.json()["expires_at"].startswith("2030-01-01")

    invalid = admin_client.post(
        "/api/v1/reservations",
        json={
            "product_id": structure["product_id"],
            "location_id": structure["location_id"],
            "quantity": "1",
            "reference": "PED-PASADO",
            "expires_at": "2020-01-01T10:00:00Z",
        },
    )
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["error"]["code"] == "invalid_expiry"

    # Force the expiry in the past: the next stock read must release it.
    reservation = db.get(StockReservation, reservation_id)
    reservation.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()

    active = admin_client.get("/api/v1/reservations?status=active")
    assert active.status_code == 200
    assert active.json()["total"] == 0

    expired = admin_client.get("/api/v1/reservations?status=expired")
    assert expired.status_code == 200
    assert expired.json()["total"] == 1
    assert expired.json()["items"][0]["status"] == "expired"

    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["reserved"]) == 0
    assert float(product["stock"]["available"]) == 10

    audit = admin_client.get("/api/v1/audit?action=reservation.expired")
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["actor_label"].startswith("Sistema")


def test_task_lifecycle_and_permissions(admin_client, worker_client, auditor_client, users):
    structure = create_structure(admin_client)
    employee_id = _link_employee(admin_client, users)

    created = admin_client.post(
        "/api/v1/tasks",
        json={
            "title": "Preparar pedido PED-2026-0001",
            "description": "Recoger 4 cajas del pasillo P04 y precintar el palé.",
            "priority": 2,
            "assigned_to": employee_id,
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["code"].startswith("AUR-TSK-")
    assert task["status"] == "pending"
    assert task["assignee_name"] == "Operario Asignado"
    assert task["priority"] == 2

    mine = worker_client.get("/api/v1/tasks?mine=true")
    assert mine.status_code == 200, mine.text
    assert mine.json()["total"] == 1
    assert mine.json()["items"][0]["id"] == task["id"]

    started = worker_client.post(f"/api/v1/tasks/{task['id']}/start")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"

    completed = worker_client.post(f"/api/v1/tasks/{task['id']}/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "done"
    assert completed.json()["completed_at"]

    # Un trabajador no crea tareas ni modifica las ajenas.
    assert (
        worker_client.post("/api/v1/tasks", json={"title": "No permitida"}).status_code == 403
    )
    foreign = admin_client.post("/api/v1/tasks", json={"title": "Tarea sin asignar"})
    assert foreign.status_code == 201
    foreign_task = foreign.json()
    denied = worker_client.post(f"/api/v1/tasks/{foreign_task['id']}/complete")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"

    # No se cancela una tarea cerrada; el responsable la reabre y la cancela.
    assert admin_client.post(f"/api/v1/tasks/{task['id']}/cancel").status_code == 409
    reopened = admin_client.post(f"/api/v1/tasks/{task['id']}/reopen")
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "pending"
    assert reopened.json()["completed_at"] is None
    cancelled = admin_client.post(f"/api/v1/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    # El auditor solo lee.
    assert auditor_client.get("/api/v1/tasks").status_code == 200
    assert auditor_client.post("/api/v1/tasks", json={"title": "Auditor no crea"}).status_code == 403

    # Filtros básicos y trazabilidad.
    done = admin_client.get("/api/v1/tasks?status=done")
    assert done.status_code == 200
    assert done.json()["total"] == 0
    audit = admin_client.get("/api/v1/audit?entity_type=task")
    assert audit.status_code == 200
    actions = {entry["action"] for entry in audit.json()["items"]}
    assert {"task.created", "task.started", "task.completed", "task.reopened"} <= actions
