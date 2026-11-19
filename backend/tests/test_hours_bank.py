"""Bolsa de horas: saldo real, ajustes justificados y permisos."""

from __future__ import annotations

from datetime import timedelta

from app.core.timeutils import madrid_day_bounds_utc, to_madrid, utcnow


def _employee(admin_client, weekly_hours=56):
    response = admin_client.post(
        "/api/v1/employees",
        json={
            "first_name": "Bruno",
            "last_name": "Horas",
            "department": "Almacén",
            "position": "Mozo de almacén",
            "status": "active",
            "weekly_hours": weekly_hours,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _link_worker(admin_client, users, employee_id):
    response = admin_client.patch(
        f"/api/v1/users/{users['worker'].id}", json={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text


def _punches(admin_client, employee_id, day):
    start, _ = madrid_day_bounds_utc(day)
    payloads = [
        ("clock_in", start + timedelta(hours=8)),
        ("break_start", start + timedelta(hours=12)),
        ("break_end", start + timedelta(hours=12, minutes=30)),
        ("clock_out", start + timedelta(hours=16)),
    ]
    for event_type, moment in payloads:
        response = admin_client.post(
            "/api/v1/attendance",
            json={"employee_id": employee_id, "event_type": event_type, "occurred_at": moment.isoformat()},
        )
        assert response.status_code == 201, response.text


def test_hours_bank_balance_and_adjustments(admin_client, worker_client, auditor_client, users):
    employee = _employee(admin_client, weekly_hours=56)
    assert employee["weekly_hours"] == "56.00"
    _link_worker(admin_client, users, employee["id"])

    yesterday = (to_madrid(utcnow()) or utcnow()).date() - timedelta(days=1)
    _punches(admin_client, employee["id"], yesterday)

    query = f"date_from={yesterday}&date_to={yesterday}"
    summary = admin_client.get(f"/api/v1/hours-bank?{query}")
    assert summary.status_code == 200, summary.text
    row = summary.json()["items"][0]
    assert row["worked_minutes"] == 450
    assert row["contracted_minutes"] == 480
    assert row["balance_minutes"] == -30
    assert summary.json()["totals"]["balance_minutes"] == -30

    mine = worker_client.get(f"/api/v1/hours-bank/me?{query}")
    assert mine.status_code == 200, mine.text
    assert mine.json()["items"][0]["employee_id"] == employee["id"]
    assert mine.json()["items"][0]["balance_minutes"] == -30

    adjustment = admin_client.post(
        "/api/v1/hours-bank/adjustments",
        json={
            "employee_id": employee["id"],
            "effective_date": yesterday.isoformat(),
            "minutes": 60,
            "reason": "Compensación por inventario nocturno",
        },
    )
    assert adjustment.status_code == 201, adjustment.text
    assert adjustment.json()["minutes"] == 60
    assert adjustment.json()["employee_code"] == employee["code"]

    summary = admin_client.get(f"/api/v1/hours-bank?{query}").json()["items"][0]
    assert summary["adjustments_minutes"] == 60
    assert summary["balance_minutes"] == 30

    listing = admin_client.get(f"/api/v1/hours-bank/adjustments?employee_id={employee['id']}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert auditor_client.get("/api/v1/hours-bank/adjustments").status_code == 200
    assert worker_client.get("/api/v1/hours-bank/adjustments").status_code == 403
    assert (
        worker_client.post(
            "/api/v1/hours-bank/adjustments",
            json={
                "employee_id": employee["id"],
                "effective_date": yesterday.isoformat(),
                "minutes": 30,
                "reason": "Sin permiso",
            },
        ).status_code
        == 403
    )

    deleted = admin_client.delete(f"/api/v1/hours-bank/adjustments/{adjustment.json()['id']}")
    assert deleted.status_code == 200
    assert admin_client.get(f"/api/v1/hours-bank?{query}").json()["items"][0][
        "balance_minutes"
    ] == -30


def test_hours_bank_validation_and_contract_update(admin_client, worker_client, users):
    employee = _employee(admin_client, weekly_hours=40)
    _link_worker(admin_client, users, employee["id"])

    zero = admin_client.post(
        "/api/v1/hours-bank/adjustments",
        json={
            "employee_id": employee["id"],
            "effective_date": (to_madrid(utcnow()) or utcnow()).date().isoformat(),
            "minutes": 0,
            "reason": "Cero no permitido",
        },
    )
    assert zero.status_code == 422

    today = (to_madrid(utcnow()) or utcnow()).date()
    far_future = admin_client.post(
        "/api/v1/hours-bank/adjustments",
        json={
            "employee_id": employee["id"],
            "effective_date": (today + timedelta(days=60)).isoformat(),
            "minutes": 30,
            "reason": "Demasiado futuro",
        },
    )
    assert far_future.status_code == 409
    assert far_future.json()["error"]["code"] == "invalid_effective_date"

    too_long = admin_client.get(
        f"/api/v1/hours-bank?date_from={(today - timedelta(days=120)).isoformat()}&date_to={today.isoformat()}"
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "range_too_long"

    updated = admin_client.patch(
        f"/api/v1/employees/{employee['id']}", json={"weekly_hours": 20}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["weekly_hours"] == "20.00"

    no_employee = worker_client.get("/api/v1/hours-bank/me")
    assert no_employee.status_code == 200
    assert no_employee.json()["items"][0]["contracted_minutes"] > 0
