"""Bolsa de horas: trabajado frente a contrato semanal y ajustes justificados."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AttendanceEventType, EmployeeStatus
from app.core.errors import ValidationError
from app.core.timeutils import ensure_utc, madrid_day_bounds_utc, to_madrid, utcnow
from app.models import AttendanceRecord, Employee, HoursBankAdjustment

_STATE_AFTER = {
    ("out", AttendanceEventType.CLOCK_IN): "in",
    ("in", AttendanceEventType.BREAK_START): "break",
    ("in", AttendanceEventType.CLOCK_OUT): "out",
    ("break", AttendanceEventType.BREAK_END): "in",
    ("break", AttendanceEventType.CLOCK_OUT): "out",
}


def worked_minutes(records: list[AttendanceRecord], reference: datetime) -> int:
    state = "out"
    last: datetime | None = None
    worked = 0.0
    for record in records:
        moment = ensure_utc(record.occurred_at) or reference
        if state == "in" and last is not None:
            worked += (moment - last).total_seconds() / 60
        next_state = _STATE_AFTER.get((state, record.event_type))
        if next_state is not None:
            state = next_state
            last = moment
    if state == "in" and last is not None and reference > last:
        worked += (reference - last).total_seconds() / 60
    return int(round(max(worked, 0)))


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def adjustments_for(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: str | None = None,
) -> list[HoursBankAdjustment]:
    stmt = select(HoursBankAdjustment)
    if date_from:
        stmt = stmt.where(HoursBankAdjustment.effective_date >= date_from)
    if date_to:
        stmt = stmt.where(HoursBankAdjustment.effective_date <= date_to)
    if employee_id:
        stmt = stmt.where(HoursBankAdjustment.employee_id == employee_id)
    return list(
        db.scalars(
            stmt.order_by(HoursBankAdjustment.effective_date.desc(), HoursBankAdjustment.created_at.desc())
        ).all()
    )


def summarize(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    employee_id: str | None = None,
) -> dict[str, Any]:
    if date_from > date_to:
        raise ValidationError("La fecha inicial no puede ser posterior a la final.", code="invalid_range")
    if (date_to - date_from).days > 92:
        raise ValidationError("El periodo máximo de la bolsa de horas es de 93 días.", code="range_too_long")

    employees_stmt = select(Employee).where(Employee.status == EmployeeStatus.ACTIVE)
    if employee_id:
        employees_stmt = employees_stmt.where(Employee.id == employee_id)
    employees = list(db.scalars(employees_stmt.order_by(Employee.code)).all())
    ids = [employee.id for employee in employees]
    if not ids:
        return {"date_from": date_from, "date_to": date_to, "items": [], "totals": {}}

    start, _ = madrid_day_bounds_utc(date_from)
    _, end = madrid_day_bounds_utc(date_to)
    records = list(
        db.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.employee_id.in_(ids),
                AttendanceRecord.occurred_at >= start,
                AttendanceRecord.occurred_at <= end,
            )
            .order_by(AttendanceRecord.occurred_at.asc())
        ).all()
    )
    by_employee_day: dict[tuple[str, date], list[AttendanceRecord]] = {}
    for record in records:
        local = to_madrid(record.occurred_at)
        if local is None:
            continue
        by_employee_day.setdefault((record.employee_id, local.date()), []).append(record)

    adjustments = adjustments_for(
        db, date_from=date_from, date_to=date_to, employee_id=employee_id
    )
    adjustment_totals: dict[str, int] = {}
    for adjustment in adjustments:
        adjustment_totals[adjustment.employee_id] = (
            adjustment_totals.get(adjustment.employee_id, 0) + adjustment.minutes
        )

    now = utcnow()
    items = []
    total_worked = total_contracted = total_adjustments = 0
    for employee in employees:
        weekly_minutes = int(round(float(employee.weekly_hours) * 60))
        weeks: dict[date, dict[str, int]] = {}
        for (emp_id, day), day_records in by_employee_day.items():
            if emp_id != employee.id:
                continue
            week = _week_start(day)
            _, day_end = madrid_day_bounds_utc(day)
            minutes = worked_minutes(day_records, min(now, day_end))
            entry = weeks.setdefault(week, {"worked": 0, "days": 0})
            entry["worked"] += minutes
            entry["days"] += 1

        contracted = 0
        worked = sum(entry["worked"] for entry in weeks.values())
        cursor = _week_start(date_from)
        while cursor <= date_to:
            days_in_period = 0
            for offset in range(7):
                candidate = cursor + timedelta(days=offset)
                if date_from <= candidate <= date_to:
                    days_in_period += 1
            contracted += int(round(weekly_minutes * days_in_period / 7))
            cursor += timedelta(days=7)

        adjusted = adjustment_totals.get(employee.id, 0)
        balance = worked - contracted + adjusted
        total_worked += worked
        total_contracted += contracted
        total_adjustments += adjusted
        items.append(
            {
                "employee_id": employee.id,
                "employee_code": employee.code,
                "employee_name": employee.full_name,
                "weekly_hours": employee.weekly_hours,
                "worked_minutes": worked,
                "contracted_minutes": contracted,
                "adjustments_minutes": adjusted,
                "balance_minutes": balance,
                "days_worked": sum(entry["days"] for entry in weeks.values()),
            }
        )

    return {
        "date_from": date_from,
        "date_to": date_to,
        "items": items,
        "totals": {
            "worked_minutes": total_worked,
            "contracted_minutes": total_contracted,
            "adjustments_minutes": total_adjustments,
            "balance_minutes": total_worked - total_contracted + total_adjustments,
        },
    }
