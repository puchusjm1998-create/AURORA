"""Programaciones de informes: CRUD, estado de SMTP y envío manual."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import AppError, ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.models import ReportSchedule, User
from app.schemas import (
    Page,
    ReportScheduleConfig,
    ReportScheduleCreate,
    ReportScheduleRead,
    ReportScheduleRun,
    ReportScheduleUpdate,
)
from app.services.audit import record_audit
from app.services.mailer import MailDeliveryError, MailNotConfigured
from app.services.report_delivery import (
    due_schedules,
    mark_failed,
    next_occurrence,
    send_schedule,
    smtp_status,
)

router = APIRouter(prefix="/report-schedules", tags=["Informes programados"])


def _get(db: Session, schedule_id: str) -> ReportSchedule:
    schedule = db.get(ReportSchedule, schedule_id)
    if schedule is None:
        raise NotFoundError("Programación", schedule_id)
    return schedule


def _read(schedule: ReportSchedule) -> ReportScheduleRead:
    data = ReportScheduleRead.model_validate(schedule)
    return data.model_copy(
        update={"creator_name": schedule.creator.full_name if schedule.creator else None}
    )


def _next_run(schedule: ReportSchedule, now) -> None:
    if not schedule.is_active:
        schedule.next_run_at = None
        return
    schedule.next_run_at = next_occurrence(
        schedule.frequency, schedule.hour_utc, schedule.weekday,
        schedule.day_of_month, after=now,
    )


def _audit(db: Session, schedule: ReportSchedule, user: User, meta: RequestMeta, action: str, **after) -> None:
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action=action,
        entity_type="report_schedule",
        entity_id=schedule.id,
        after={"name": schedule.name, "kind": schedule.report_kind.value, **after},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )


@router.get("", response_model=Page[ReportScheduleRead], summary="Listar programaciones")
def list_schedules(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
    active: bool | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ReportScheduleRead]:
    stmt = select(ReportSchedule)
    if active is not None:
        stmt = stmt.where(ReportSchedule.is_active.is_(active))
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(ReportSchedule.name.ilike(term), ReportSchedule.last_error.ilike(term))
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(ReportSchedule.is_active.desc(), ReportSchedule.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(items=[_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/config", response_model=ReportScheduleConfig, summary="Estado del correo saliente")
def config(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
) -> ReportScheduleConfig:
    status = smtp_status()
    active = int(
        db.scalar(
            select(func.count()).select_from(ReportSchedule).where(ReportSchedule.is_active.is_(True))
        )
        or 0
    )
    return ReportScheduleConfig(**status, active=active, due=len(due_schedules(db)))


@router.post("", response_model=ReportScheduleRead, status_code=201, summary="Crear programación")
def create_schedule(
    payload: ReportScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ReportScheduleRead:
    schedule = ReportSchedule(
        name=payload.name,
        report_kind=payload.report_kind,
        report_format=payload.report_format,
        frequency=payload.frequency,
        weekday=payload.weekday if payload.frequency.value == "weekly" else None,
        day_of_month=payload.day_of_month if payload.frequency.value == "monthly" else None,
        hour_utc=payload.hour_utc,
        recipients=payload.recipients,
        is_active=payload.is_active,
        created_by=user.id,
    )
    _next_run(schedule, utcnow())
    db.add(schedule)
    db.flush()
    _audit(db, schedule, user, meta, "report_schedule.created",
           frequency=schedule.frequency.value, recipients=schedule.recipients)
    db.commit()
    db.refresh(schedule)
    return _read(schedule)


@router.patch("/{schedule_id}", response_model=ReportScheduleRead, summary="Modificar programación")
def update_schedule(
    schedule_id: str,
    payload: ReportScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ReportScheduleRead:
    schedule = _get(db, schedule_id)
    merged = {
        "name": schedule.name,
        "report_kind": schedule.report_kind,
        "report_format": schedule.report_format,
        "frequency": schedule.frequency,
        "weekday": schedule.weekday,
        "day_of_month": schedule.day_of_month,
        "hour_utc": schedule.hour_utc,
        "recipients": schedule.recipients,
        "is_active": schedule.is_active,
        **payload.model_dump(exclude_unset=True),
    }
    try:
        validated = ReportScheduleCreate(**merged)
    except PydanticValidationError as exc:
        raise ValidationError(
            "La programación no es válida.",
            details={"fields": [{"field": ".".join(map(str, error["loc"])),
                                 "message": error["msg"]} for error in exc.errors()]},
        ) from exc
    before = {"is_active": schedule.is_active, "frequency": schedule.frequency.value,
              "recipients": schedule.recipients}
    for field, value in validated.model_dump().items():
        setattr(schedule, field, value)
    schedule.weekday = validated.weekday if validated.frequency.value == "weekly" else None
    schedule.day_of_month = (
        validated.day_of_month if validated.frequency.value == "monthly" else None
    )
    _next_run(schedule, utcnow())
    _audit(db, schedule, user, meta, "report_schedule.updated",
           before=before, recipients=schedule.recipients, is_active=schedule.is_active)
    db.commit()
    db.refresh(schedule)
    return _read(schedule)


@router.delete("/{schedule_id}", status_code=204, summary="Eliminar programación")
def delete_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Response:
    schedule = _get(db, schedule_id)
    _audit(db, schedule, user, meta, "report_schedule.deleted")
    db.delete(schedule)
    db.commit()
    return Response(status_code=204)


@router.post("/{schedule_id}/run", response_model=ReportScheduleRun, summary="Enviar ahora")
def run_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.REPORTS_EXPORT)),
    meta: RequestMeta = Depends(get_request_meta),
) -> ReportScheduleRun:
    schedule = _get(db, schedule_id)
    if not smtp_status()["configured"]:
        raise ConflictError(
            "El correo saliente no está configurado. Defina SMTP_HOST y sus credenciales.",
            code="smtp_not_configured",
        )
    try:
        message_id = send_schedule(db, schedule, advance=False)
    except MailNotConfigured as exc:  # pragma: no cover - cubierto por la comprobación anterior
        raise ConflictError(str(exc), code="smtp_not_configured") from exc
    except MailDeliveryError as exc:
        mark_failed(db, schedule, str(exc), advance=False)
        db.commit()
        raise AppError(str(exc), status_code=502, code="mail_delivery_failed") from exc
    _audit(db, schedule, user, meta, "report_schedule.run_now",
           recipients=schedule.recipients, message_id=message_id)
    db.commit()
    db.refresh(schedule)
    return ReportScheduleRun(status="sent", message_id=message_id, detail="Informe enviado")
