"""Attendance: clock in/out, breaks and worked-time summaries.

The punch log is append-only: corrections are new punches, never edits or
deletions. Sequence rules are enforced on the server (you cannot clock out if
you are not clocked in, cannot start a break twice, ...), so the state shown in
the UI can always be derived from the immutable records.

Workers may only punch their own employee record; supervisors with
``attendance.manage`` can register a punch on behalf of a worker (for example a
forgotten badge) and the audit log records who did it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_any_permission, require_permission
from app.api.serializers import employee_brief
from app.core.db import get_db
from app.core.enums import AttendanceEventType, EmployeeStatus, PermissionCode
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.permissions import permissions_for_role
from app.core.timeutils import (
    ensure_utc,
    madrid_day_bounds_utc,
    to_madrid,
    utcnow,
)
from app.models import AttendanceRecord, Employee, User
from app.schemas import (
    AttendanceCreate,
    AttendanceMe,
    AttendanceRead,
    AttendanceSummary,
    AttendanceSummaryRow,
    Page,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/attendance", tags=["Fichaje"])

# Allowed next event for each state.
ALLOWED: dict[str, set[AttendanceEventType]] = {
    "out": {AttendanceEventType.CLOCK_IN},
    "in": {AttendanceEventType.BREAK_START, AttendanceEventType.CLOCK_OUT},
    "break": {AttendanceEventType.BREAK_END, AttendanceEventType.CLOCK_OUT},
}

STATE_AFTER: dict[tuple[str, AttendanceEventType], str] = {
    ("out", AttendanceEventType.CLOCK_IN): "in",
    ("in", AttendanceEventType.BREAK_START): "break",
    ("in", AttendanceEventType.CLOCK_OUT): "out",
    ("break", AttendanceEventType.BREAK_END): "in",
    ("break", AttendanceEventType.CLOCK_OUT): "out",
}

EVENT_LABEL = {
    AttendanceEventType.CLOCK_IN: "fichar entrada",
    AttendanceEventType.CLOCK_OUT: "fichar salida",
    AttendanceEventType.BREAK_START: "iniciar pausa",
    AttendanceEventType.BREAK_END: "finalizar pausa",
}


def _to_read(record: AttendanceRecord) -> AttendanceRead:
    employee = record.employee
    return AttendanceRead(
        id=record.id,
        employee_id=record.employee_id,
        employee_name=f"{employee.first_name} {employee.last_name}" if employee else "",
        employee_code=employee.code if employee else "",
        event_type=record.event_type,
        occurred_at=record.occurred_at,
        recorded_at=record.recorded_at,
        source=record.source,
        device_label=record.device_label,
        note=record.note,
    )


def _walk(records: Iterable[AttendanceRecord], reference: datetime) -> tuple[str, datetime | None, int, int]:
    """Return (state, since, worked_minutes, break_minutes) for a sorted log."""
    state = "out"
    last: datetime | None = None
    worked = 0.0
    breaks = 0.0
    for record in records:
        moment = ensure_utc(record.occurred_at) or reference
        if state != "out" and last is not None:
            minutes = (moment - last).total_seconds() / 60
            if state == "in":
                worked += minutes
            else:
                breaks += minutes
        next_state = STATE_AFTER.get((state, record.event_type))
        if next_state is not None:
            state = next_state
            last = moment
    if state != "out" and last is not None and reference > last:
        minutes = (reference - last).total_seconds() / 60
        if state == "in":
            worked += minutes
        else:
            breaks += minutes
    return state, (last if state != "out" else None), int(round(max(worked, 0))), int(round(max(breaks, 0)))


def _records_for(
    db: Session,
    employee_id: str,
    start: datetime,
    end: datetime,
) -> list[AttendanceRecord]:
    return list(
        db.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.occurred_at >= start,
                AttendanceRecord.occurred_at <= end,
            )
            .order_by(AttendanceRecord.occurred_at.asc())
        ).all()
    )


def _own_employee(user: User) -> Employee:
    if user.employee is None:
        raise ConflictError(
            "Su cuenta no está vinculada a una ficha de empleado. Pida al administrador que la vincule.",
            code="employee_not_linked",
        )
    return user.employee


@router.get("/me", response_model=AttendanceMe, summary="Mi jornada")
def my_attendance(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_CLOCK)),
    day: date | None = None,
) -> AttendanceMe:
    employee = _own_employee(user)
    now = utcnow()
    target_day = day or (to_madrid(now).date() if to_madrid(now) else now.date())
    start, end = madrid_day_bounds_utc(target_day)
    today_records = _records_for(db, employee.id, start, end)
    state, since, worked, breaks = _walk(today_records, min(now, end))

    week_start_day = target_day - timedelta(days=target_day.weekday())
    week_start, _ = madrid_day_bounds_utc(week_start_day)
    _, week_last_end = madrid_day_bounds_utc(week_start_day + timedelta(days=6))
    week_records = _records_for(db, employee.id, week_start, min(now, week_last_end))
    week_minutes = 0
    by_day: dict[date, list[AttendanceRecord]] = {}
    for record in week_records:
        local = to_madrid(record.occurred_at)
        if local is not None:
            by_day.setdefault(local.date(), []).append(record)
    for local_day, day_records in by_day.items():
        _, day_end = madrid_day_bounds_utc(local_day)
        _, _, day_worked, _ = _walk(day_records, min(now, day_end))
        week_minutes += day_worked

    return AttendanceMe(
        employee=employee_brief(employee),
        date=target_day,
        state=state,
        since=since,
        worked_minutes=worked,
        break_minutes=breaks,
        today=[_to_read(record) for record in reversed(today_records)],
        week_minutes=week_minutes,
    )


@router.get("", response_model=Page[AttendanceRead], summary="Listar fichajes")
def list_attendance(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.ATTENDANCE_READ)),
    employee_id: str | None = None,
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[AttendanceRead]:
    stmt = select(AttendanceRecord)
    if employee_id:
        stmt = stmt.where(AttendanceRecord.employee_id == employee_id)
    if event_type:
        stmt = stmt.where(AttendanceRecord.event_type == event_type)
    if date_from:
        start, _ = madrid_day_bounds_utc(date_from)
        stmt = stmt.where(AttendanceRecord.occurred_at >= start)
    if date_to:
        _, end = madrid_day_bounds_utc(date_to)
        stmt = stmt.where(AttendanceRecord.occurred_at <= end)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(AttendanceRecord.occurred_at.desc()).limit(limit).offset(offset)
        ).all()
    )
    return Page(items=[_to_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=AttendanceSummary, summary="Resumen de horas")
def attendance_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.ATTENDANCE_READ)),
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: str | None = None,
) -> AttendanceSummary:
    today = to_madrid(utcnow())
    current = today.date() if today else utcnow().date()
    end_day = date_to or current
    start_day = date_from or (end_day - timedelta(days=6))
    if start_day > end_day:
        raise ValidationError("La fecha inicial no puede ser posterior a la final.")
    if (end_day - start_day).days > 92:
        raise ValidationError("El periodo máximo del resumen es de 93 días.")

    start, _ = madrid_day_bounds_utc(start_day)
    _, end = madrid_day_bounds_utc(end_day)
    stmt = select(AttendanceRecord).where(
        AttendanceRecord.occurred_at >= start,
        AttendanceRecord.occurred_at <= end,
    )
    if employee_id:
        stmt = stmt.where(AttendanceRecord.employee_id == employee_id)
    records = list(
        db.scalars(stmt.order_by(AttendanceRecord.occurred_at.asc())).all()
    )

    grouped: dict[tuple[str, date], list[AttendanceRecord]] = {}
    employees: dict[str, Employee] = {}
    for record in records:
        local = to_madrid(record.occurred_at)
        if local is None:
            continue
        grouped.setdefault((record.employee_id, local.date()), []).append(record)
        if record.employee is not None:
            employees[record.employee_id] = record.employee

    now = utcnow()
    totals: dict[str, dict[str, object]] = {}
    for (emp_id, day), day_records in grouped.items():
        _, day_end = madrid_day_bounds_utc(day)
        _, _, worked, breaks = _walk(day_records, min(now, day_end))
        entry = totals.setdefault(
            emp_id,
            {
                "days": set(),
                "worked": 0,
                "breaks": 0,
                "first_in": None,
                "last_out": None,
            },
        )
        cast_days: set[date] = entry["days"]  # type: ignore[assignment]
        cast_days.add(day)
        entry["worked"] = int(entry["worked"]) + worked  # type: ignore[call-overload]
        entry["breaks"] = int(entry["breaks"]) + breaks  # type: ignore[call-overload]
        for record in day_records:
            if record.event_type == AttendanceEventType.CLOCK_IN:
                moment = ensure_utc(record.occurred_at)
                if moment and (entry["first_in"] is None or moment < entry["first_in"]):  # type: ignore[operator]
                    entry["first_in"] = moment
            if record.event_type == AttendanceEventType.CLOCK_OUT:
                moment = ensure_utc(record.occurred_at)
                if moment and (entry["last_out"] is None or moment > entry["last_out"]):  # type: ignore[operator]
                    entry["last_out"] = moment

    items: list[AttendanceSummaryRow] = []
    for emp_id, entry in totals.items():
        employee = employees.get(emp_id)
        items.append(
            AttendanceSummaryRow(
                employee_id=emp_id,
                employee_code=employee.code if employee else "",
                employee_name=(
                    f"{employee.first_name} {employee.last_name}" if employee else ""
                ),
                days=len(entry["days"]),  # type: ignore[arg-type]
                worked_minutes=int(entry["worked"]),  # type: ignore[call-overload]
                break_minutes=int(entry["breaks"]),  # type: ignore[call-overload]
                first_in=entry["first_in"],  # type: ignore[arg-type]
                last_out=entry["last_out"],  # type: ignore[arg-type]
            )
        )
    items.sort(key=lambda row: row.worked_minutes, reverse=True)
    return AttendanceSummary(
        date_from=start_day,
        date_to=end_day,
        total_worked_minutes=sum(row.worked_minutes for row in items),
        items=items,
    )


@router.post("", response_model=AttendanceRead, status_code=201, summary="Registrar fichaje")
def create_attendance(
    payload: AttendanceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_any_permission(
            PermissionCode.ATTENDANCE_MANAGE,
            PermissionCode.ATTENDANCE_CLOCK,
        )
    ),
    meta: RequestMeta = Depends(get_request_meta),
) -> AttendanceRead:
    granted = permissions_for_role(db, user.role_id)
    manage = PermissionCode.ATTENDANCE_MANAGE.value in granted
    own = user.employee
    target_id = payload.employee_id or (own.id if own else None)
    if target_id is None:
        raise ConflictError(
            "Su cuenta no está vinculada a una ficha de empleado. Pida al administrador que la vincule.",
            code="employee_not_linked",
        )
    if not manage and (own is None or target_id != own.id):
        raise PermissionDeniedError("Solo puede fichar su propia jornada.")

    employee = db.get(Employee, target_id)
    if employee is None:
        raise NotFoundError("Trabajador", target_id)
    if employee.status == EmployeeStatus.INACTIVE:
        raise ValidationError("No se pueden registrar fichajes de un trabajador inactivo.")

    now = utcnow()
    if manage:
        occurred = ensure_utc(payload.occurred_at) or now
        if occurred > now + timedelta(minutes=5):
            raise ValidationError("La hora del fichaje no puede estar en el futuro.")
        source = "manual"
    else:
        occurred = now
        source = "web"

    history = list(
        db.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.employee_id == target_id,
                AttendanceRecord.occurred_at < occurred,
            )
            .order_by(AttendanceRecord.occurred_at.asc())
        ).all()
    )
    state, _, _, _ = _walk(history, occurred)
    if payload.event_type not in ALLOWED[state]:
        raise ConflictError(
            f"No se puede {EVENT_LABEL[payload.event_type]} en el estado actual "
            f"({ { 'out': 'fuera de turno', 'in': 'trabajando', 'break': 'en pausa' }[state] }).",
            code="invalid_attendance_sequence",
            details={"state": state, "event_type": payload.event_type.value},
        )
    next_record = db.scalars(
        select(AttendanceRecord)
        .where(
            AttendanceRecord.employee_id == target_id,
            AttendanceRecord.occurred_at > occurred,
        )
        .order_by(AttendanceRecord.occurred_at.asc())
    ).first()
    if next_record is not None:
        after = STATE_AFTER[(state, payload.event_type)]
        if next_record.event_type not in ALLOWED[after]:
            raise ConflictError(
                "El fichaje rompe la secuencia con los registros posteriores de ese día.",
                code="invalid_attendance_sequence",
                details={"next_event": next_record.event_type.value},
            )

    record = AttendanceRecord(
        employee_id=target_id,
        event_type=payload.event_type,
        occurred_at=occurred,
        source=source,
        device_label=(payload.device_label or "").strip() or None,
        note=payload.note.strip(),
        created_by=user.id,
    )
    db.add(record)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="attendance.recorded",
        entity_type="attendance_record",
        entity_id=record.id,
        after={
            "employee_code": employee.code,
            "employee_id": employee.id,
            "event_type": payload.event_type.value,
            "occurred_at": occurred.isoformat(),
            "source": source,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(record)
    return _to_read(record)
