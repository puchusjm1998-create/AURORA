"""Attendance: own punch clock, manager records, summaries and RBAC."""

from __future__ import annotations

from datetime import timedelta

from app.core.timeutils import madrid_day_bounds_utc, to_madrid, utcnow


def _link_employee(admin_client, users, email="worker@test.local"):
    employee = admin_client.post(
        "/api/v1/employees",
        json={
            "first_name": "Operario",
            "last_name": "Fichaje",
            "department": "Almacén",
            "position": "Mozo de almacén",
            "status": "active",
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]
    linked = admin_client.patch(
        f"/api/v1/users/{users['worker'].id}", json={"employee_id": employee_id}
    )
    assert linked.status_code == 200, linked.text
    return employee_id


def test_worker_punches_own_day(worker_client, auditor_client, users, admin_client):
    _link_employee(admin_client, users)

    start = worker_client.get("/api/v1/attendance/me")
    assert start.status_code == 200, start.text
    assert start.json()["state"] == "out"
    assert start.json()["employee"]["first_name"] == "Operario"

    clock_in = worker_client.post("/api/v1/attendance", json={"event_type": "clock_in"})
    assert clock_in.status_code == 201, clock_in.text
    assert clock_in.json()["source"] == "web"
    state = worker_client.get("/api/v1/attendance/me").json()
    assert state["state"] == "in"
    assert state["since"] is not None

    duplicate = worker_client.post("/api/v1/attendance", json={"event_type": "clock_in"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "invalid_attendance_sequence"

    assert (
        worker_client.post("/api/v1/attendance", json={"event_type": "break_start"}).json()["event_type"]
        == "break_start"
    )
    assert worker_client.get("/api/v1/attendance/me").json()["state"] == "break"
    assert (
        worker_client.post("/api/v1/attendance", json={"event_type": "break_end"}).json()["event_type"]
        == "break_end"
    )
    assert worker_client.get("/api/v1/attendance/me").json()["state"] == "in"
    assert (
        worker_client.post("/api/v1/attendance", json={"event_type": "clock_out"}).json()["event_type"]
        == "clock_out"
    )
    final = worker_client.get("/api/v1/attendance/me").json()
    assert final["state"] == "out"
    assert len(final["today"]) == 4

    assert (
        worker_client.post("/api/v1/attendance", json={"event_type": "clock_out"}).status_code
        == 409
    )

    # No puede fichar por otra persona ni consultar el fichaje de todos.
    assert (
        worker_client.post(
            "/api/v1/attendance",
            json={"employee_id": "otra-persona", "event_type": "clock_in"},
        ).status_code
        == 403
    )
    assert worker_client.get("/api/v1/attendance").status_code == 403

    # El auditor consulta pero no ficha.
    assert auditor_client.get("/api/v1/attendance").status_code == 200
    assert (
        auditor_client.post("/api/v1/attendance", json={"event_type": "clock_in"}).status_code
        == 403
    )


def test_manager_manual_records_and_summary(admin_client, users):
    employee_id = _link_employee(admin_client, users)
    yesterday = (to_madrid(utcnow()) or utcnow()).date() - timedelta(days=1)
    start, _ = madrid_day_bounds_utc(yesterday)
    payloads = [
        ("clock_in", start + timedelta(hours=8)),
        ("break_start", start + timedelta(hours=12)),
        ("break_end", start + timedelta(hours=12, minutes=30)),
        ("clock_out", start + timedelta(hours=16)),
    ]
    for event_type, moment in payloads:
        response = admin_client.post(
            "/api/v1/attendance",
            json={
                "employee_id": employee_id,
                "event_type": event_type,
                "occurred_at": moment.isoformat(),
                "note": "Fichaje recuperado por olvido de tarjeta",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["source"] == "manual"

    summary = admin_client.get(
        f"/api/v1/attendance/summary?date_from={yesterday}&date_to={yesterday}"
    )
    assert summary.status_code == 200, summary.text
    data = summary.json()
    assert data["items"][0]["worked_minutes"] == 450
    assert data["items"][0]["break_minutes"] == 30
    assert data["items"][0]["days"] == 1
    assert data["items"][0]["first_in"] and data["items"][0]["last_out"]

    listed = admin_client.get(f"/api/v1/attendance?employee_id={employee_id}")
    assert listed.status_code == 200
    assert listed.json()["total"] == 4

    # Un fichaje intermedio incompatible rompe la secuencia.
    conflict = admin_client.post(
        "/api/v1/attendance",
        json={
            "employee_id": employee_id,
            "event_type": "clock_in",
            "occurred_at": (start + timedelta(hours=9)).isoformat(),
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "invalid_attendance_sequence"

    future = admin_client.post(
        "/api/v1/attendance",
        json={
            "employee_id": employee_id,
            "event_type": "clock_in",
            "occurred_at": (utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert future.status_code == 422

    audit = admin_client.get("/api/v1/audit?action=attendance.recorded")
    assert audit.status_code == 200
    assert audit.json()["total"] == 4
