"""Planificación semanal de turnos, cobertura y solapes."""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import create_structure


def _employee(admin_client, name="Ana"):
    response = admin_client.post(
        "/api/v1/employees",
        json={
            "first_name": name,
            "last_name": "Turnos",
            "department": "Almacén",
            "position": "Mozo de almacén",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def test_shift_planning_assignment_and_coverage(admin_client, worker_client):
    structure = create_structure(admin_client)
    employee = _employee(admin_client)

    created = admin_client.post(
        "/api/v1/shifts",
        json={
            "warehouse_id": structure["warehouse_id"],
            "name": "Mañana",
            "start_time": "06:00",
            "end_time": "14:00",
            "days_of_week": [0, 1, 2, 3, 4],
            "required_headcount": 2,
        },
    )
    assert created.status_code == 201, created.text
    shift = created.json()
    assert shift["days_of_week"] == [0, 1, 2, 3, 4]
    assert shift["warehouse_code"] == "ALM-01"

    assert worker_client.post(
        "/api/v1/shifts",
        json={
            "warehouse_id": structure["warehouse_id"],
            "name": "Sin permiso",
            "start_time": "08:00",
            "end_time": "12:00",
            "days_of_week": [0],
        },
    ).status_code == 403
    assert worker_client.get("/api/v1/shifts").status_code == 403

    monday = _next_monday()
    assignment = admin_client.post(
        f"/api/v1/shifts/{shift['id']}/assignments",
        json={"employee_id": employee["id"], "work_date": monday.isoformat(), "note": "Primer día"},
    )
    assert assignment.status_code == 201, assignment.text
    assert assignment.json()["employee_name"] == "Ana Turnos"
    assert assignment.json()["shift_name"] == "Mañana"

    duplicate = admin_client.post(
        f"/api/v1/shifts/{shift['id']}/assignments",
        json={"employee_id": employee["id"], "work_date": monday.isoformat()},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_assignment"

    evening = admin_client.post(
        "/api/v1/shifts",
        json={
            "warehouse_id": structure["warehouse_id"],
            "name": "Tarde",
            "start_time": "13:00",
            "end_time": "21:00",
            "days_of_week": [0],
            "required_headcount": 1,
        },
    )
    assert evening.status_code == 201
    overlap = admin_client.post(
        f"/api/v1/shifts/{evening.json()['id']}/assignments",
        json={"employee_id": employee["id"], "work_date": monday.isoformat()},
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "shift_overlap"

    plan = admin_client.get(
        "/api/v1/shifts/plan",
        params={"date_from": monday.isoformat(), "date_to": (monday + timedelta(days=6)).isoformat()},
    )
    assert plan.status_code == 200, plan.text
    data = plan.json()
    assert len(data["days"]) == 7
    assert data["total_assignments"] == 1
    assert data["uncovered_shifts"] == 6
    monday_plan = data["days"][0]
    assert monday_plan["weekday"] == 0
    assert len(monday_plan["shifts"]) == 2
    morning = next(row for row in monday_plan["shifts"] if row["name"] == "Mañana")
    assert morning["assigned_count"] == 1
    assert morning["missing"] == 1
    assert morning["assigned"][0]["employee_name"] == "Ana Turnos"

    blocked = admin_client.delete(f"/api/v1/shifts/{shift['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "shift_has_assignments"

    assignment_id = assignment.json()["id"]
    assert admin_client.delete(
        f"/api/v1/shifts/{shift['id']}/assignments/{assignment_id}"
    ).status_code == 204
    assert admin_client.delete(f"/api/v1/shifts/{shift['id']}").status_code == 204


def test_shift_validation(admin_client):
    structure = create_structure(admin_client)

    invalid_hours = admin_client.post(
        "/api/v1/shifts",
        json={
            "warehouse_id": structure["warehouse_id"],
            "name": "Imposible",
            "start_time": "18:00",
            "end_time": "08:00",
            "days_of_week": [0],
        },
    )
    assert invalid_hours.status_code == 422
    assert invalid_hours.json()["error"]["code"] == "invalid_shift_hours"

    invalid_days = admin_client.post(
        "/api/v1/shifts",
        json={
            "warehouse_id": structure["warehouse_id"],
            "name": "Días",
            "start_time": "08:00",
            "end_time": "16:00",
            "days_of_week": [9],
        },
    )
    assert invalid_days.status_code == 422

    shift = admin_client.post(
        "/api/v1/shifts",
        json={
            "warehouse_id": structure["warehouse_id"],
            "name": "Pausable",
            "start_time": "08:00",
            "end_time": "16:00",
            "days_of_week": [0],
            "required_headcount": 1,
        },
    ).json()
    employee = _employee(admin_client, "Luis")
    wrong_day = admin_client.post(
        f"/api/v1/shifts/{shift['id']}/assignments",
        json={"employee_id": employee["id"], "work_date": (_next_monday() + timedelta(days=1)).isoformat()},
    )
    assert wrong_day.status_code == 422
    assert wrong_day.json()["error"]["code"] == "weekday_not_scheduled"

    paused = admin_client.patch(
        f"/api/v1/shifts/{shift['id']}", json={"is_active": False}
    )
    assert paused.status_code == 200
    assert paused.json()["is_active"] is False

    paused_assignment = admin_client.post(
        f"/api/v1/shifts/{shift['id']}/assignments",
        json={"employee_id": employee["id"], "work_date": _next_monday().isoformat()},
    )
    assert paused_assignment.status_code == 409
    assert paused_assignment.json()["error"]["code"] == "shift_inactive"

    plan = admin_client.get(
        "/api/v1/shifts/plan",
        params={"date_from": _next_monday().isoformat(), "date_to": _next_monday().isoformat()},
    )
    assert plan.status_code == 200
    assert plan.json()["days"][0]["shifts"] == []

    too_long = admin_client.get(
        "/api/v1/shifts/plan",
        params={
            "date_from": _next_monday().isoformat(),
            "date_to": (_next_monday() + timedelta(days=90)).isoformat(),
        },
    )
    assert too_long.status_code == 422
