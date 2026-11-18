"""Fase 8: registro de llamadas y handoff SIP/API.

Modos de funcionamiento, configurables por entorno:

* ``handoff``: el servidor devuelve enlaces ``tel:`` y, si hay dominio SIP,
  ``sip:``; la llamada la abre el softphone o el marcador del dispositivo.
* ``webhook``: el servidor envía la orden a un proveedor HTTP/SIP configurado.
  Sin URL no se inventa una llamada: se responde 503.
* ``disabled``: no se permite registrar llamadas.

El registro es una tabla de llamadas con estado, resultado y auditoría; no se
almacena audio ni se afirma que una llamada se haya cursado si el proveedor no
lo confirma.
"""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import CallStatus, PermissionCode
from app.core.errors import AppError, ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.models import CallRecord, Incident, User
from app.schemas import (
    CallCreate,
    CallRead,
    CallUpdate,
    Page,
    TelephonyStatus,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/calls", tags=["Llamadas"])
settings = get_settings()

TERMINAL = {CallStatus.COMPLETED.value, CallStatus.FAILED.value}


def _normalise_phone(raw: str) -> str:
    candidate = re.sub(r"[^\d+]", "", raw)
    if candidate.count("+") > 1 or ("+" in candidate and not candidate.startswith("+")):
        raise ValidationError("Teléfono no válido.", code="invalid_phone")
    digits = candidate.lstrip("+")
    if not 7 <= len(digits) <= 15:
        raise ValidationError(
            "El teléfono debe tener entre 7 y 15 dígitos.", code="invalid_phone"
        )
    return f"+{digits}" if candidate.startswith("+") else digits


def _sip_uri(phone: str) -> str | None:
    domain = settings.telephony_sip_domain.strip()
    if not domain:
        return None
    return f"sip:{phone}@{domain}"


def _to_read(call: CallRecord) -> CallRead:
    tel_uri = f"tel:{call.phone}"
    sip_uri = _sip_uri(call.phone)
    return CallRead(
        id=call.id,
        contact_name=call.contact_name,
        phone=call.phone,
        purpose=call.purpose,
        status=CallStatus(call.status),
        provider=call.provider,
        provider_call_id=call.provider_call_id,
        incident_id=call.incident_id,
        authorized_by=call.authorizer.full_name if call.authorizer else None,
        created_by=call.creator.full_name if call.creator else None,
        started_at=call.started_at,
        ended_at=call.ended_at,
        result=call.result,
        created_at=call.created_at,
        tel_uri=tel_uri,
        sip_uri=sip_uri,
        dial_uri=sip_uri or tel_uri,
    )


@router.get("/config", response_model=TelephonyStatus, summary="Estado de la telefonía")
def telephony_status(
    _: User = Depends(require_permission(PermissionCode.CALLS_MANAGE)),
) -> TelephonyStatus:
    mode = settings.telephony_mode.strip().lower()
    if mode not in {"handoff", "webhook", "disabled"}:
        mode = "disabled"
    if mode == "webhook":
        message = (
            "Las llamadas se envían al proveedor HTTP configurado."
            if settings.telephony_can_originate
            else "Modo webhook sin TELEPHONY_WEBHOOK_URL: no se pueden originar llamadas."
        )
    elif mode == "handoff":
        message = (
            "La llamada se abre en el softphone o marcador del dispositivo (handoff). "
            "El servidor no origina la llamada."
        )
    else:
        message = "La telefonía está desactivada en este despliegue."
    return TelephonyStatus(
        mode=mode,
        sip_domain=settings.telephony_sip_domain.strip(),
        sip_extension=settings.telephony_sip_extension.strip(),
        webhook_configured=bool(settings.telephony_webhook_url.strip()),
        can_originate=settings.telephony_can_originate,
        message=message,
    )


@router.get("", response_model=Page[CallRead], summary="Listar llamadas")
def list_calls(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.CALLS_MANAGE)),
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[CallRead]:
    stmt = select(CallRecord)
    if status:
        stmt = stmt.where(CallRecord.status == status)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            CallRecord.contact_name.ilike(term) | CallRecord.phone.ilike(term)
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(stmt.order_by(CallRecord.created_at.desc()).limit(limit).offset(offset)).all()
    )
    return Page(items=[_to_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/{call_id}", response_model=CallRead, summary="Detalle de llamada")
def get_call(
    call_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.CALLS_MANAGE)),
) -> CallRead:
    call = db.get(CallRecord, call_id)
    if call is None:
        raise NotFoundError("Llamada", call_id)
    return _to_read(call)


def _send_webhook(call: CallRecord) -> tuple[str | None, str, str]:
    """Send the call to an HTTP telephony gateway; return (provider id, status, error)."""
    headers = {"Content-Type": "application/json"}
    if settings.telephony_webhook_token.strip():
        headers["Authorization"] = f"Bearer {settings.telephony_webhook_token.strip()}"
    payload = {
        "to": call.phone,
        "contact_name": call.contact_name,
        "purpose": call.purpose,
        "reference": call.id,
        "extension": settings.telephony_sip_extension.strip() or None,
    }
    try:
        response = httpx.post(
            settings.telephony_webhook_url.strip(),
            json=payload,
            headers=headers,
            timeout=settings.telephony_webhook_timeout,
        )
    except httpx.HTTPError as exc:
        return None, CallStatus.FAILED.value, f"No se pudo contactar con el proveedor: {exc}"
    if response.status_code >= 400:
        return (
            None,
            CallStatus.FAILED.value,
            f"El proveedor respondió HTTP {response.status_code}.",
        )
    try:
        data = response.json()
    except ValueError:
        data = {}
    provider_id = str(data.get("call_id") or data.get("id") or data.get("sid") or "") or None
    reported = str(data.get("status") or "").lower()
    status = reported if reported in {s.value for s in CallStatus} else CallStatus.QUEUED.value
    if status in {CallStatus.HANDOFF.value, CallStatus.COMPLETED.value, CallStatus.FAILED.value}:
        status = CallStatus.QUEUED.value
    return provider_id, status, ""


@router.post("", response_model=CallRead, status_code=201, summary="Registrar y cursar llamada")
def create_call(
    payload: CallCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.CALLS_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> CallRead:
    mode = settings.telephony_mode.strip().lower()
    if mode == "disabled" or mode not in {"handoff", "webhook"}:
        raise AppError(
            "La telefonía está desactivada en este despliegue.",
            status_code=503,
            code="telephony_disabled",
        )
    if payload.incident_id and db.get(Incident, payload.incident_id) is None:
        raise NotFoundError("Incidencia", payload.incident_id)
    phone = _normalise_phone(payload.phone)
    now = utcnow()
    call = CallRecord(
        incident_id=payload.incident_id,
        contact_name=payload.contact_name.strip(),
        phone=phone,
        purpose=payload.purpose.strip(),
        provider="sip-handoff" if mode == "handoff" else "webhook",
        status=CallStatus.HANDOFF.value if mode == "handoff" else CallStatus.QUEUED.value,
        authorized_by=user.id,
        created_by=user.id,
        started_at=now if mode == "handoff" else None,
    )
    db.add(call)
    db.flush()

    if mode == "webhook":
        if not settings.telephony_can_originate:
            db.rollback()
            raise AppError(
                "El proveedor telefónico no está configurado (TELEPHONY_WEBHOOK_URL).",
                status_code=503,
                code="telephony_not_configured",
            )
        provider_id, status, error = _send_webhook(call)
        call.provider_call_id = provider_id
        call.status = status
        call.started_at = utcnow()
        if error:
            call.status = CallStatus.FAILED.value
            call.result = error[:2000]
            db.flush()
            record_audit(
                db,
                actor_user_id=user.id,
                actor_label=user.full_name,
                action="call.failed",
                entity_type="call",
                entity_id=call.id,
                after={"phone": phone, "error": error},
                ip=meta.ip,
                user_agent=meta.user_agent,
            )
            db.commit()
            raise AppError(
                error,
                status_code=502,
                code="telephony_provider_error",
                details={"call_id": call.id},
            )

    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="call.created",
        entity_type="call",
        entity_id=call.id,
        after={"phone": phone, "mode": mode, "provider_call_id": call.provider_call_id},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(call)
    return _to_read(call)


@router.patch("/{call_id}", response_model=CallRead, summary="Cerrar o actualizar llamada")
def update_call(
    call_id: str,
    payload: CallUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.CALLS_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> CallRead:
    call = db.get(CallRecord, call_id)
    if call is None:
        raise NotFoundError("Llamada", call_id)
    if call.status in TERMINAL:
        raise ConflictError("La llamada ya está cerrada.", code="call_closed")
    call.status = payload.status
    call.result = payload.result.strip()
    if payload.status in TERMINAL:
        call.ended_at = utcnow()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="call.updated",
        entity_type="call",
        entity_id=call.id,
        after={"status": payload.status, "result": call.result},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(call)
    return _to_read(call)
