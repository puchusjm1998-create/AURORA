"""Tarjetas NFC: emisión, revocación y fichaje por lectura.

El token de la tarjeta es un secreto: solo se devuelve al emitirla y en la base
de datos únicamente queda su hash SHA-256 y los últimos cuatro caracteres.
Una tarjeta revocada no puede fichar; el histórico de fichajes es inmutable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    RequestMeta,
    ensure_employee_access,
    get_request_meta,
    require_permission,
)
from app.core.db import get_db
from app.core.enums import NfcCardStatus, PermissionCode
from app.core.errors import ConflictError, NotFoundError
from app.core.timeutils import utcnow
from app.models import Employee, NfcCard, User
from app.schemas import (
    Message,
    NfcCardCreate,
    NfcCardIssued,
    NfcCardRead,
    NfcTapRead,
    NfcTapRequest,
    Page,
)
from app.services.audit import record_audit
from app.services.nfc import (
    EVENT_LABEL,
    current_state,
    issue_token,
    resolve_card,
    tap_card,
)

router = APIRouter(prefix="/nfc", tags=["Tarjetas NFC"])


def _to_read(card: NfcCard) -> NfcCardRead:
    employee = card.employee
    return NfcCardRead(
        id=card.id,
        employee_id=card.employee_id,
        employee_code=employee.code if employee else "",
        employee_name=f"{employee.first_name} {employee.last_name}" if employee else "",
        label=card.label,
        token_last4=card.token_last4,
        status=card.status,
        last_used_at=card.last_used_at,
        revoked_at=card.revoked_at,
        created_at=card.created_at,
    )


@router.get("/cards", response_model=Page[NfcCardRead], summary="Listar tarjetas NFC")
def list_cards(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.ATTENDANCE_MANAGE)),
    employee_id: str | None = None,
    status: NfcCardStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[NfcCardRead]:
    stmt = select(NfcCard)
    if employee_id:
        stmt = stmt.where(NfcCard.employee_id == employee_id)
    if status:
        stmt = stmt.where(NfcCard.status == status)
    cards = list(
        db.scalars(stmt.order_by(NfcCard.created_at.desc()).limit(limit).offset(offset)).all()
    )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    return Page(items=[_to_read(card) for card in cards], total=total, limit=limit, offset=offset)


@router.post("/cards", response_model=NfcCardIssued, status_code=201, summary="Emitir tarjeta NFC")
def issue_card(
    payload: NfcCardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> NfcCardIssued:
    employee = db.get(Employee, payload.employee_id)
    if employee is None:
        raise NotFoundError("Trabajador", payload.employee_id)
    active = db.scalars(
        select(NfcCard).where(
            NfcCard.employee_id == employee.id, NfcCard.status == NfcCardStatus.ACTIVE
        )
    ).first()
    if active is not None:
        raise ConflictError(
            "El trabajador ya tiene una tarjeta NFC activa; revóquela antes de emitir otra.",
            code="employee_has_active_card",
            details={"card_id": active.id},
        )
    token, token_hash, last4 = issue_token()
    card = NfcCard(
        employee_id=employee.id,
        label=payload.label or f"Tarjeta {employee.code}",
        token_hash=token_hash,
        token_last4=last4,
        status=NfcCardStatus.ACTIVE,
        created_by=user.id,
    )
    db.add(card)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.email,
        action="nfc.card.issue",
        entity_type="nfc_card",
        entity_id=card.id,
        after={"employee_id": employee.id, "token_last4": last4},
        ip=meta.ip,
    )
    db.commit()
    db.refresh(card)
    base = _to_read(card)
    return NfcCardIssued(**base.model_dump(), token=token)


@router.post("/cards/{card_id}/revoke", response_model=NfcCardRead, summary="Revocar tarjeta NFC")
def revoke_card(
    card_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> NfcCardRead:
    card = db.get(NfcCard, card_id)
    if card is None:
        raise NotFoundError("Tarjeta NFC", card_id)
    if card.status == NfcCardStatus.REVOKED:
        raise ConflictError("La tarjeta ya está revocada.", code="card_already_revoked")
    card.status = NfcCardStatus.REVOKED
    card.revoked_at = utcnow()
    card.revoked_by = user.id
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.email,
        action="nfc.card.revoke",
        entity_type="nfc_card",
        entity_id=card.id,
        before={"status": "active"},
        after={"status": "revoked"},
        ip=meta.ip,
    )
    db.commit()
    db.refresh(card)
    return _to_read(card)


@router.post("/tap", response_model=NfcTapRead, summary="Fichar leyendo una tarjeta NFC")
def tap(
    payload: NfcTapRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_CLOCK)),
    meta: RequestMeta = Depends(get_request_meta),
) -> NfcTapRead:
    card = resolve_card(db, payload.token)
    ensure_employee_access(db, user, card.employee_id)
    card, record, state = tap_card(
        db, token=payload.token, action=payload.action, note=payload.note
    )
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.email,
        action="attendance.nfc.tap",
        entity_type="attendance_record",
        entity_id=record.id,
        after={"employee_id": record.employee_id, "event": record.event_type.value},
        ip=meta.ip,
    )
    db.commit()
    db.refresh(record)
    employee = card.employee
    return NfcTapRead(
        card_id=card.id,
        card_label=card.label,
        employee=employee,
        event_type=record.event_type,
        event_label=EVENT_LABEL[record.event_type],
        occurred_at=record.occurred_at,
        state=state,
        message=f"{EVENT_LABEL[record.event_type]} para {employee.first_name} {employee.last_name}.",
    )


@router.get("/cards/{card_id}", response_model=NfcCardRead, summary="Consultar tarjeta NFC")
def get_card(
    card_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.ATTENDANCE_MANAGE)),
) -> NfcCardRead:
    card = db.get(NfcCard, card_id)
    if card is None:
        raise NotFoundError("Tarjeta NFC", card_id)
    return _to_read(card)


@router.get("/state/{employee_id}", response_model=dict, summary="Estado de fichaje del trabajador")
def employee_state(
    employee_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_CLOCK)),
) -> dict:
    ensure_employee_access(db, user, employee_id)
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Trabajador", employee_id)
    return {"employee_id": employee_id, "state": current_state(db, employee_id)}


@router.delete("/cards/{card_id}", response_model=Message, summary="Eliminar tarjeta revocada")
def delete_card(
    card_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.ATTENDANCE_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    card = db.get(NfcCard, card_id)
    if card is None:
        raise NotFoundError("Tarjeta NFC", card_id)
    if card.status != NfcCardStatus.REVOKED:
        raise ConflictError("Solo se pueden eliminar tarjetas revocadas.", code="card_not_revoked")
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.email,
        action="nfc.card.delete",
        entity_type="nfc_card",
        entity_id=card.id,
        before={"employee_id": card.employee_id, "token_last4": card.token_last4},
        ip=meta.ip,
    )
    db.delete(card)
    db.commit()
    return Message(message="Tarjeta eliminada.")
