"""Tarjetas NFC: emisión con token opaco y fichaje por lectura de tarjeta."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AttendanceEventType, EmployeeStatus, NfcCardStatus, NfcTapAction
from app.core.errors import ConflictError, NotFoundError
from app.core.timeutils import ensure_utc, madrid_day_bounds_utc, to_madrid, utcnow
from app.models import AttendanceRecord, Employee, NfcCard

TOKEN_PREFIX = "AUR-NFC-"
STATE_AFTER = {
    ("out", AttendanceEventType.CLOCK_IN): "in",
    ("in", AttendanceEventType.BREAK_START): "break",
    ("in", AttendanceEventType.CLOCK_OUT): "out",
    ("break", AttendanceEventType.BREAK_END): "in",
    ("break", AttendanceEventType.CLOCK_OUT): "out",
}
ACTION_EVENT = {
    NfcTapAction.CLOCK_IN: AttendanceEventType.CLOCK_IN,
    NfcTapAction.CLOCK_OUT: AttendanceEventType.CLOCK_OUT,
    NfcTapAction.BREAK_START: AttendanceEventType.BREAK_START,
    NfcTapAction.BREAK_END: AttendanceEventType.BREAK_END,
}
AUTO_EVENT = {
    "out": AttendanceEventType.CLOCK_IN,
    "in": AttendanceEventType.CLOCK_OUT,
    "break": AttendanceEventType.BREAK_END,
}
EVENT_LABEL = {
    AttendanceEventType.CLOCK_IN: "Entrada registrada",
    AttendanceEventType.CLOCK_OUT: "Salida registrada",
    AttendanceEventType.BREAK_START: "Pausa iniciada",
    AttendanceEventType.BREAK_END: "Pausa finalizada",
}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def issue_token() -> tuple[str, str, str]:
    token = TOKEN_PREFIX + secrets.token_urlsafe(24)
    return token, hash_token(token), token[-4:]


def resolve_card(db: Session, token: str) -> NfcCard:
    card = db.scalars(select(NfcCard).where(NfcCard.token_hash == hash_token(token))).first()
    if card is None:
        raise NotFoundError("Tarjeta NFC", "token no reconocido")
    if card.status == NfcCardStatus.REVOKED:
        raise ConflictError("La tarjeta está revocada.", code="card_revoked")
    return card


def current_state(db: Session, employee_id: str, now: datetime | None = None) -> str:
    moment = ensure_utc(now or utcnow()) or utcnow()
    local = to_madrid(moment) or moment
    start, end = madrid_day_bounds_utc(local.date())
    records = list(
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
    state = "out"
    for record in records:
        state = STATE_AFTER.get((state, record.event_type), state)
    return state


def tap_card(
    db: Session,
    *,
    token: str,
    action: NfcTapAction = NfcTapAction.AUTO,
    note: str = "",
    now: datetime | None = None,
) -> tuple[NfcCard, AttendanceRecord, str]:
    card = resolve_card(db, token)
    employee: Employee = card.employee
    if employee is None:
        raise NotFoundError("Empleado de la tarjeta", card.id)
    if employee.status != EmployeeStatus.ACTIVE:
        raise ConflictError("El empleado no está activo.", code="employee_inactive")

    moment = ensure_utc(now or utcnow()) or utcnow()
    state = current_state(db, employee.id, moment)
    event_type = (
        AUTO_EVENT[state] if action == NfcTapAction.AUTO else ACTION_EVENT[action]
    )
    if STATE_AFTER.get((state, event_type)) is None:
        raise ConflictError(
            f"No se puede {EVENT_LABEL[event_type].lower()} desde el estado «{state}».",
            code="invalid_sequence",
            details={"state": state, "event_type": event_type.value},
        )

    record = AttendanceRecord(
        employee_id=employee.id,
        event_type=event_type,
        occurred_at=moment,
        recorded_at=utcnow(),
        source="nfc",
        device_label=card.label or f"Tarjeta {card.token_last4}",
        note=note,
    )
    db.add(record)
    card.last_used_at = moment
    db.flush()
    return card, record, STATE_AFTER[(state, event_type)]
