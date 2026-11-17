"""Programación y envío de informes recurrentes por correo."""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import ReportFormat, ReportKind, ScheduleFrequency, ScheduleRunStatus
from app.core.timeutils import utcnow
from app.models import ReportSchedule
from app.services.audit import record_audit
from app.services.mailer import Attachment, Message, send as send_mail
from app.services.report_data import inventory_table, movements_table, table_csv_bytes
from app.services.reports import render_pdf, render_xlsx, select_columns

logger = logging.getLogger("aurora.reports")

MIME_TYPES = {
    ReportFormat.PDF: "application/pdf",
    ReportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ReportFormat.CSV: "text/csv",
}
PDF_COLUMNS = {
    ReportKind.INVENTORY: [0, 1, 4, 5, 7, 8, 9, 12],
    ReportKind.MOVEMENTS: [0, 1, 2, 4, 5, 6, 7, 8, 12],
}
KIND_LABELS = {
    ReportKind.INVENTORY: "Inventario",
    ReportKind.MOVEMENTS: "Movimientos",
}
Mailer = Callable[..., str]


def as_utc(moment: datetime) -> datetime:
    """Normaliza a UTC; SQLite devuelve datetimes sin zona."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def next_occurrence(
    frequency: ScheduleFrequency,
    hour_utc: int,
    weekday: int | None,
    day_of_month: int | None,
    after: datetime,
) -> datetime:
    """Siguiente ejecución estrictamente posterior a ``after`` (UTC)."""
    after = as_utc(after)
    base = after.replace(minute=0, second=0, microsecond=0)

    if frequency == ScheduleFrequency.DAILY:
        candidate = base.replace(hour=hour_utc)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate

    if frequency == ScheduleFrequency.WEEKLY:
        target = 0 if weekday is None else weekday
        candidate = (base + timedelta(days=(target - base.weekday()) % 7)).replace(hour=hour_utc)
        if candidate <= after:
            candidate += timedelta(days=7)
        return candidate

    day = 1 if day_of_month is None else day_of_month
    year, month = base.year, base.month
    candidate = datetime(year, month, day, hour_utc, tzinfo=timezone.utc)
    if candidate <= after:
        month += 1
        if month == 13:
            year, month = year + 1, 1
        day = min(day, calendar.monthrange(year, month)[1])
        candidate = datetime(year, month, day, hour_utc, tzinfo=timezone.utc)
    return candidate


def build_attachment(db: Session, schedule: ReportSchedule, *, now: datetime | None = None) -> Attachment:
    stamp = as_utc(now or utcnow()).date().isoformat()
    if schedule.report_kind == ReportKind.INVENTORY:
        table = inventory_table(db, None, True)
    else:
        table = movements_table(db, None, None)

    if schedule.report_format == ReportFormat.PDF:
        content = render_pdf(select_columns(table, PDF_COLUMNS[schedule.report_kind]), moment=now)
    elif schedule.report_format == ReportFormat.XLSX:
        content = render_xlsx(table, moment=now)
    else:
        content = table_csv_bytes(table)

    filename = f"aurora-{schedule.report_kind.value}-{stamp}.{schedule.report_format.value}"
    return Attachment(filename=filename, content=content, mime_type=MIME_TYPES[schedule.report_format])


def build_message(schedule: ReportSchedule, attachment: Attachment, *, now: datetime) -> Message:
    label = KIND_LABELS.get(schedule.report_kind, schedule.report_kind.value)
    subject = f"AURORA · {label} · {now.strftime('%d/%m/%Y')}"
    body = (
        f"Informe programado «{schedule.name}» generado por AURORA LOGISTICS AI.\n\n"
        f"Tipo: {label}\n"
        f"Formato: {schedule.report_format.value.upper()}\n"
        f"Generado: {now.strftime('%d/%m/%Y %H:%M')} UTC\n"
        f"Adjunto: {attachment.filename} ({len(attachment.content):,} bytes)\n\n"
        "Este mensaje se ha enviado automáticamente. Los datos proceden de la base de datos "
        "en el momento de la generación; no responda a este correo.\n"
    )
    return Message(
        to=list(schedule.recipients),
        subject=subject,
        body=body.replace(f"{len(attachment.content):,}", f"{len(attachment.content):,}".replace(",", ".")),
        attachments=[attachment],
    )


def send_schedule(
    db: Session,
    schedule: ReportSchedule,
    *,
    now: datetime | None = None,
    advance: bool = True,
    mailer: Mailer = send_mail,
) -> str:
    """Genera y envía el informe; deja la programación y la auditoría actualizadas."""
    moment = as_utc(now or utcnow())
    attachment = build_attachment(db, schedule, now=moment)
    message = build_message(schedule, attachment, now=moment)
    message_id = mailer(message)

    schedule.last_run_at = moment
    schedule.last_status = ScheduleRunStatus.SENT
    schedule.last_error = ""
    if advance:
        schedule.next_run_at = next_occurrence(
            schedule.frequency, schedule.hour_utc, schedule.weekday,
            schedule.day_of_month, after=moment,
        )
    record_audit(
        db,
        actor_user_id=None,
        actor_label="scheduler",
        action="report_schedule.sent",
        entity_type="report_schedule",
        entity_id=schedule.id,
        after={
            "recipients": list(schedule.recipients),
            "format": schedule.report_format.value,
            "message_id": message_id,
            "bytes": len(attachment.content),
        },
    )
    return message_id


def mark_failed(
    db: Session,
    schedule: ReportSchedule,
    error: str,
    *,
    now: datetime | None = None,
    advance: bool = True,
) -> None:
    moment = as_utc(now or utcnow())
    schedule.last_run_at = moment
    schedule.last_status = ScheduleRunStatus.FAILED
    schedule.last_error = error[:500]
    if advance:
        schedule.next_run_at = next_occurrence(
            schedule.frequency, schedule.hour_utc, schedule.weekday,
            schedule.day_of_month, after=moment,
        )
    record_audit(
        db,
        actor_user_id=None,
        actor_label="scheduler",
        action="report_schedule.failed",
        entity_type="report_schedule",
        entity_id=schedule.id,
        after={"error": schedule.last_error},
    )


def due_schedules(db: Session, now: datetime | None = None) -> list[ReportSchedule]:
    moment = as_utc(now or utcnow())
    return list(
        db.scalars(
            select(ReportSchedule)
            .where(ReportSchedule.is_active.is_(True))
            .where(ReportSchedule.next_run_at.is_not(None))
            .where(ReportSchedule.next_run_at <= moment)
            .order_by(ReportSchedule.next_run_at)
        ).all()
    )


def process_due(
    db: Session,
    *,
    now: datetime | None = None,
    mailer: Mailer = send_mail,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Envía los informes vencidos. Nunca aborta por el fallo de uno solo."""
    moment = as_utc(now or utcnow())
    results: list[dict[str, str]] = []
    for schedule in due_schedules(db, moment)[: limit or None]:
        try:
            message_id = send_schedule(db, schedule, now=moment, mailer=mailer)
            results.append(
                {"id": schedule.id, "name": schedule.name, "status": "sent", "detail": message_id}
            )
        except Exception as exc:  # noqa: BLE001 - se registra y se continúa con el resto
            logger.exception("Fallo al enviar el informe programado %s", schedule.name)
            mark_failed(db, schedule, str(exc), now=moment)
            results.append(
                {"id": schedule.id, "name": schedule.name, "status": "failed", "detail": str(exc)}
            )
        db.commit()
    return results


def smtp_status() -> dict[str, object]:
    settings = get_settings()
    return {
        "configured": settings.smtp_configured,
        "host": settings.smtp_host or None,
        "port": settings.smtp_port if settings.smtp_configured else None,
        "from_address": settings.smtp_from if settings.smtp_configured else None,
        "starttls": settings.smtp_starttls,
        "ssl": settings.smtp_ssl,
    }
