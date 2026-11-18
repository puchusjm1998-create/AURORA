"""Planificación semanal de turnos y control de solapes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EmployeeStatus
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.models import Employee, ShiftAssignment, User, Warehouse, WorkShift

WEEKDAY_LABELS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def validate_schedule(
    db: Session,
    *,
    warehouse_id: str,
    start_time,
    end_time,
    days_of_week: list[int],
) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", warehouse_id)
    if not warehouse.is_active:
        raise ConflictError("El almacén está inactivo.", code="warehouse_inactive")
    if start_time >= end_time:
        raise ValidationError(
            "La hora de fin debe ser posterior a la de inicio (no se admiten turnos nocturnos partidos).",
            code="invalid_shift_hours",
        )
    if not days_of_week:
        raise ValidationError("Seleccione al menos un día de la semana.", code="no_days")
    if any(day < 0 or day > 6 for day in days_of_week):
        raise ValidationError("Día de la semana no válido.", code="invalid_day")
    return warehouse


def assign_employee(
    db: Session,
    shift: WorkShift,
    *,
    employee_id: str,
    work_date: date,
    note: str = "",
    created_by: str | None = None,
) -> ShiftAssignment:
    if not shift.is_active:
        raise ConflictError("El turno está pausado.", code="shift_inactive")
    if work_date.weekday() not in shift.days_of_week:
        raise ValidationError(
            f"El turno no se planifica los {WEEKDAY_LABELS[work_date.weekday()]}.",
            code="weekday_not_scheduled",
        )
    today = utcnow().date()
    if work_date > today + timedelta(days=365) or work_date < today - timedelta(days=90):
        raise ValidationError(
            "La fecha debe estar entre 90 días atrás y un año vista.", code="date_out_of_range"
        )
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Empleado", employee_id)
    if employee.status != EmployeeStatus.ACTIVE:
        raise ConflictError("El empleado no está activo.", code="employee_inactive")

    duplicate = db.scalars(
        select(ShiftAssignment).where(
            ShiftAssignment.shift_id == shift.id,
            ShiftAssignment.employee_id == employee.id,
            ShiftAssignment.work_date == work_date,
        )
    ).first()
    if duplicate:
        raise ConflictError(
            "Esa persona ya está asignada a este turno en esa fecha.", code="duplicate_assignment"
        )

    others = db.scalars(
        select(ShiftAssignment)
        .join(WorkShift, WorkShift.id == ShiftAssignment.shift_id)
        .where(
            ShiftAssignment.employee_id == employee.id,
            ShiftAssignment.work_date == work_date,
        )
    ).all()
    for other in others:
        if shift.start_time < other.shift.end_time and other.shift.start_time < shift.end_time:
            raise ConflictError(
                f"Solapa con el turno «{other.shift.name}» "
                f"({other.shift.start_time.strftime('%H:%M')}–{other.shift.end_time.strftime('%H:%M')}).",
                code="shift_overlap",
            )

    assignment = ShiftAssignment(
        shift_id=shift.id,
        employee_id=employee.id,
        work_date=work_date,
        note=note,
        created_by=created_by,
    )
    db.add(assignment)
    db.flush()
    return assignment


def assignment_read(assignment: ShiftAssignment) -> dict[str, Any]:
    return {
        "id": assignment.id,
        "shift_id": assignment.shift_id,
        "shift_name": assignment.shift.name,
        "employee_id": assignment.employee_id,
        "employee_code": assignment.employee.code,
        "employee_name": assignment.employee.full_name,
        "work_date": assignment.work_date,
        "note": assignment.note,
        "created_at": assignment.created_at,
    }


def shift_read(shift: WorkShift) -> dict[str, Any]:
    return {
        "id": shift.id,
        "warehouse_id": shift.warehouse_id,
        "warehouse_code": shift.warehouse.code if shift.warehouse else None,
        "warehouse_name": shift.warehouse.name if shift.warehouse else None,
        "name": shift.name,
        "start_time": shift.start_time,
        "end_time": shift.end_time,
        "days_of_week": shift.days_of_week,
        "required_headcount": shift.required_headcount,
        "is_active": shift.is_active,
        "created_at": shift.created_at,
    }


def plan(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    warehouse_id: str | None = None,
) -> dict[str, Any]:
    if date_to < date_from:
        raise ValidationError("La fecha final no puede ser anterior a la inicial.", code="invalid_range")
    if (date_to - date_from).days > 62:
        raise ValidationError("El plan admite como máximo 62 días.", code="range_too_long")

    stmt = select(WorkShift).where(WorkShift.is_active.is_(True))
    if warehouse_id:
        stmt = stmt.where(WorkShift.warehouse_id == warehouse_id)
    shifts = list(db.scalars(stmt.order_by(WorkShift.start_time, WorkShift.name)).all())

    shift_ids = [shift.id for shift in shifts]
    rows = []
    if shift_ids:
        rows = list(
            db.scalars(
                select(ShiftAssignment).where(
                    ShiftAssignment.shift_id.in_(shift_ids),
                    ShiftAssignment.work_date >= date_from,
                    ShiftAssignment.work_date <= date_to,
                )
            ).all()
        )
    assignments: dict[tuple[str, date], list[ShiftAssignment]] = {}
    for assignment in rows:
        assignments.setdefault((assignment.shift_id, assignment.work_date), []).append(assignment)

    days: list[dict[str, Any]] = []
    total_assignments = 0
    uncovered = 0
    current = date_from
    while current <= date_to:
        weekday = current.weekday()
        day_shifts = []
        for shift in shifts:
            if weekday not in shift.days_of_week:
                continue
            assigned = sorted(
                assignments.get((shift.id, current), []),
                key=lambda item: item.employee.full_name if item.employee else "",
            )
            missing = max(shift.required_headcount - len(assigned), 0)
            total_assignments += len(assigned)
            if missing:
                uncovered += 1
            day_shifts.append(
                {
                    "shift_id": shift.id,
                    "name": shift.name,
                    "start_time": shift.start_time,
                    "end_time": shift.end_time,
                    "required_headcount": shift.required_headcount,
                    "assigned_count": len(assigned),
                    "missing": missing,
                    "assigned": [assignment_read(item) for item in assigned],
                }
            )
        days.append({"work_date": current, "weekday": weekday, "shifts": day_shifts})
        current += timedelta(days=1)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "days": days,
        "total_assignments": total_assignments,
        "uncovered_shifts": uncovered,
    }


def shift_for_employee(db: Session, employee_id: str, work_date: date) -> list[ShiftAssignment]:
    return list(
        db.scalars(
            select(ShiftAssignment).where(
                ShiftAssignment.employee_id == employee_id,
                ShiftAssignment.work_date == work_date,
            )
        ).all()
    )


def audit_label(user: User) -> str:
    return user.full_name
