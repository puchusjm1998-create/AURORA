"""Planificación de turnos de trabajo por almacén."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import ShiftAssignment, User, WorkShift
from app.schemas import (
    ShiftAssignmentCreate,
    ShiftAssignmentRead,
    ShiftCreate,
    ShiftDayPlan,
    ShiftPlan,
    ShiftPlanRow,
    ShiftRead,
    ShiftUpdate,
)
from app.services.audit import record_audit
from app.services.shifts import (
    WEEKDAY_LABELS,
    assign_employee,
    assignment_read,
    plan as build_plan,
    shift_read,
    validate_schedule,
)

router = APIRouter(prefix="/shifts", tags=["Turnos"])


def _shift(db: Session, shift_id: str) -> WorkShift:
    shift = db.get(WorkShift, shift_id)
    if shift is None:
        raise NotFoundError("Turno", shift_id)
    return shift


@router.get("", response_model=list[ShiftRead], summary="Listar turnos")
def list_shifts(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.WORKERS_READ)),
    warehouse_id: str | None = None,
    include_inactive: bool = True,
) -> list[ShiftRead]:
    stmt = select(WorkShift)
    if warehouse_id:
        stmt = stmt.where(WorkShift.warehouse_id == warehouse_id)
    if not include_inactive:
        stmt = stmt.where(WorkShift.is_active.is_(True))
    return [
        ShiftRead(**shift_read(shift))
        for shift in db.scalars(stmt.order_by(WorkShift.start_time, WorkShift.name)).all()
    ]


@router.get("/plan", response_model=ShiftPlan, summary="Plan de turnos por fechas")
def shift_plan(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.WORKERS_READ)),
    date_from: date = Query(...),
    date_to: date = Query(...),
    warehouse_id: str | None = None,
) -> ShiftPlan:
    data = build_plan(
        db, date_from=date_from, date_to=date_to, warehouse_id=warehouse_id
    )
    return ShiftPlan(
        date_from=data["date_from"],
        date_to=data["date_to"],
        total_assignments=data["total_assignments"],
        uncovered_shifts=data["uncovered_shifts"],
        days=[
            ShiftDayPlan(
                work_date=day["work_date"],
                weekday=day["weekday"],
                shifts=[ShiftPlanRow(**row) for row in day["shifts"]],
            )
            for day in data["days"]
        ],
    )


@router.post("", response_model=ShiftRead, status_code=201, summary="Crear turno")
def create_shift(
    payload: ShiftCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.WORKERS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ShiftRead:
    validate_schedule(
        db,
        warehouse_id=payload.warehouse_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        days_of_week=payload.days_of_week,
    )
    duplicate = db.scalars(
        select(WorkShift).where(
            WorkShift.warehouse_id == payload.warehouse_id,
            WorkShift.name == payload.name.strip(),
        )
    ).first()
    if duplicate:
        raise ConflictError("Ya existe un turno con ese nombre en el almacén.", code="duplicate_shift")
    shift = WorkShift(
        warehouse_id=payload.warehouse_id,
        name=payload.name.strip(),
        start_time=payload.start_time,
        end_time=payload.end_time,
        days_of_week=payload.days_of_week,
        required_headcount=payload.required_headcount,
        created_by=user.id,
    )
    db.add(shift)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="shift.created",
        entity_type="work_shift",
        entity_id=shift.id,
        after={
            "name": shift.name,
            "warehouse_id": shift.warehouse_id,
            "start": shift.start_time.isoformat(),
            "end": shift.end_time.isoformat(),
            "days": shift.days_of_week,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(shift)
    return ShiftRead(**shift_read(shift))


@router.patch("/{shift_id}", response_model=ShiftRead, summary="Modificar turno")
def update_shift(
    shift_id: str,
    payload: ShiftUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.WORKERS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ShiftRead:
    shift = _shift(db, shift_id)
    changes = payload.model_dump(exclude_unset=True)
    start_time = changes.get("start_time", shift.start_time)
    end_time = changes.get("end_time", shift.end_time)
    days = changes.get("days_of_week", shift.days_of_week)
    if not days or any(day < 0 or day > 6 for day in days):
        raise ValidationError("Días de la semana no válidos.", code="invalid_day")
    days = sorted(set(days))
    validate_schedule(
        db,
        warehouse_id=shift.warehouse_id,
        start_time=start_time,
        end_time=end_time,
        days_of_week=days,
    )
    if "days_of_week" in changes:
        orphaned = [
            assignment
            for assignment in shift.assignments
            if assignment.work_date.weekday() not in days
        ]
        if orphaned:
            sample = orphaned[0]
            raise ConflictError(
                f"Hay {len(orphaned)} asignación(es) en días que se quieren quitar "
                f"(por ejemplo {sample.work_date.isoformat()}, "
                f"{WEEKDAY_LABELS[sample.work_date.weekday()]}). Elimínelas antes.",
                code="assignments_on_removed_day",
            )
    if "name" in changes:
        changes["name"] = str(changes["name"]).strip()
        duplicate = db.scalars(
            select(WorkShift).where(
                WorkShift.warehouse_id == shift.warehouse_id,
                WorkShift.name == changes["name"],
                WorkShift.id != shift.id,
            )
        ).first()
        if duplicate:
            raise ConflictError("Ya existe un turno con ese nombre.", code="duplicate_shift")
    changes["days_of_week"] = days
    for field, value in changes.items():
        setattr(shift, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="shift.updated",
        entity_type="work_shift",
        entity_id=shift.id,
        after={key: str(value) for key, value in changes.items()},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(shift)
    return ShiftRead(**shift_read(shift))


@router.delete("/{shift_id}", status_code=204, summary="Eliminar turno sin asignaciones")
def delete_shift(
    shift_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.WORKERS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Response:
    shift = _shift(db, shift_id)
    count = int(
        db.scalar(
            select(func.count())
            .select_from(ShiftAssignment)
            .where(ShiftAssignment.shift_id == shift.id)
        )
        or 0
    )
    if count:
        raise ConflictError(
            "El turno tiene asignaciones; pausarlo evita perder el historial.",
            code="shift_has_assignments",
        )
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="shift.deleted",
        entity_type="work_shift",
        entity_id=shift.id,
        after={"name": shift.name},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.delete(shift)
    db.commit()
    return Response(status_code=204)


@router.post(
    "/{shift_id}/assignments",
    response_model=ShiftAssignmentRead,
    status_code=201,
    summary="Asignar persona a un turno",
)
def create_assignment(
    shift_id: str,
    payload: ShiftAssignmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.WORKERS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ShiftAssignmentRead:
    shift = _shift(db, shift_id)
    assignment = assign_employee(
        db,
        shift,
        employee_id=payload.employee_id,
        work_date=payload.work_date,
        note=payload.note,
        created_by=user.id,
    )
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="shift.assigned",
        entity_type="shift_assignment",
        entity_id=assignment.id,
        after={
            "shift": shift.name,
            "employee_id": assignment.employee_id,
            "work_date": assignment.work_date.isoformat(),
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(assignment)
    return ShiftAssignmentRead(**assignment_read(assignment))


@router.delete(
    "/{shift_id}/assignments/{assignment_id}",
    status_code=204,
    summary="Quitar asignación",
)
def delete_assignment(
    shift_id: str,
    assignment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.WORKERS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Response:
    assignment = db.get(ShiftAssignment, assignment_id)
    if assignment is None or assignment.shift_id != shift_id:
        raise NotFoundError("Asignación", assignment_id)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="shift.unassigned",
        entity_type="shift_assignment",
        entity_id=assignment.id,
        after={
            "shift": assignment.shift.name,
            "employee_id": assignment.employee_id,
            "work_date": assignment.work_date.isoformat(),
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.delete(assignment)
    db.commit()
    return Response(status_code=204)
