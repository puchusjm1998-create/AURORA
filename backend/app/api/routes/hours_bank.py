"""Bolsa de horas: saldo por trabajador y ajustes manuales trazables.

El saldo se calcula con los fichajes reales (sin editar el histórico) menos la
jornada teórica del periodo (``employees.weekly_hours`` prorrateada por días) y
más los ajustes manuales justificados. Un saldo positivo son horas a favor del
trabajador; uno negativo, horas pendientes de compensar.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, ensure_employee_access, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.timeutils import to_madrid, utcnow
from app.models import Employee, HoursBankAdjustment, User
from app.schemas import (
    HoursBankAdjustmentCreate,
    HoursBankAdjustmentRead,
    HoursBankSummary,
    Message,
    Page,
)
from app.services.audit import record_audit
from app.services.hours_bank import adjustments_for, summarize

router = APIRouter(prefix="/hours-bank", tags=["Bolsa de horas"])


def _month_start() -> date:
    today = (to_madrid(utcnow()) or utcnow()).date()
    return today.replace(day=1)


def _adjustment_read(adjustment: HoursBankAdjustment) -> HoursBankAdjustmentRead:
    employee = adjustment.employee
    return HoursBankAdjustmentRead(
        id=adjustment.id,
        employee_id=adjustment.employee_id,
        employee_code=employee.code if employee else "",
        employee_name=f"{employee.first_name} {employee.last_name}" if employee else "",
        effective_date=adjustment.effective_date,
        minutes=adjustment.minutes,
        reason=adjustment.reason,
        created_at=adjustment.created_at,
    )


@router.get("", response_model=HoursBankSummary, summary="Saldo de la bolsa de horas")
def get_hours_bank(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.ATTENDANCE_READ)),
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: str | None = None,
) -> HoursBankSummary:
    start = date_from or _month_start()
    end = date_to or (to_madrid(utcnow()) or utcnow()).date()
    return HoursBankSummary(**summarize(db, date_from=start, date_to=end, employee_id=employee_id))


@router.get("/me", response_model=HoursBankSummary, summary="Mi bolsa de horas")
def get_my_hours_bank(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_CLOCK)),
    date_from: date | None = None,
    date_to: date | None = None,
) -> HoursBankSummary:
    if user.employee is None:
        raise PermissionDeniedError("Su usuario no tiene ficha de trabajador asociada.")
    start = date_from or _month_start()
    end = date_to or (to_madrid(utcnow()) or utcnow()).date()
    return HoursBankSummary(
        **summarize(db, date_from=start, date_to=end, employee_id=user.employee.id)
    )


@router.get(
    "/adjustments", response_model=Page[HoursBankAdjustmentRead], summary="Listar ajustes de horas"
)
def list_adjustments(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.ATTENDANCE_READ)),
    employee_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> Page[HoursBankAdjustmentRead]:
    items = adjustments_for(
        db, date_from=date_from, date_to=date_to, employee_id=employee_id
    )[:limit]
    return Page(
        items=[_adjustment_read(item) for item in items],
        total=len(items),
        limit=limit,
        offset=0,
    )


@router.post(
    "/adjustments",
    response_model=HoursBankAdjustmentRead,
    status_code=201,
    summary="Registrar un ajuste de horas",
)
def create_adjustment(
    payload: HoursBankAdjustmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> HoursBankAdjustmentRead:
    employee = db.get(Employee, payload.employee_id)
    if employee is None:
        raise NotFoundError("Trabajador", payload.employee_id)
    today = (to_madrid(utcnow()) or utcnow()).date()
    if payload.effective_date > today + timedelta(days=31):
        raise ConflictError(
            "El ajuste no puede tener una fecha futura superior a un mes.",
            code="invalid_effective_date",
        )
    if payload.effective_date < today - timedelta(days=366):
        raise ConflictError(
            "El ajuste no puede ser anterior a un año.", code="invalid_effective_date"
        )
    adjustment = HoursBankAdjustment(
        employee_id=employee.id,
        effective_date=payload.effective_date,
        minutes=payload.minutes,
        reason=payload.reason,
        created_by=user.id,
    )
    db.add(adjustment)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.email,
        action="hours_bank.adjustment.create",
        entity_type="hours_bank_adjustment",
        entity_id=adjustment.id,
        after={
            "employee_id": employee.id,
            "minutes": payload.minutes,
            "effective_date": payload.effective_date.isoformat(),
        },
        ip=meta.ip,
    )
    db.commit()
    db.refresh(adjustment)
    return _adjustment_read(adjustment)


@router.delete(
    "/adjustments/{adjustment_id}", response_model=Message, summary="Eliminar un ajuste de horas"
)
def delete_adjustment(
    adjustment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    adjustment = db.get(HoursBankAdjustment, adjustment_id)
    if adjustment is None:
        raise NotFoundError("Ajuste de horas", adjustment_id)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.email,
        action="hours_bank.adjustment.delete",
        entity_type="hours_bank_adjustment",
        entity_id=adjustment.id,
        before={
            "employee_id": adjustment.employee_id,
            "minutes": adjustment.minutes,
            "reason": adjustment.reason,
        },
        ip=meta.ip,
    )
    db.delete(adjustment)
    db.commit()
    return Message(message="Ajuste eliminado.")
