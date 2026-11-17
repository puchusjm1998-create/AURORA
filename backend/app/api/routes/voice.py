"""Consultas de voz: el navegador transcribe; el servidor responde con datos reales."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.models import User
from app.schemas import Message, VoiceQuery, VoiceResponse
from app.services.voice import answer, provider_status

router = APIRouter(prefix="/voice", tags=["AURORA Voice"])
settings = get_settings()


@router.get("/status", response_model=Message, summary="Capacidades de voz")
def voice_status(
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> Message:
    status = provider_status()
    status["locale"] = settings.voice_locale
    status["configured_provider"] = settings.voice_provider
    return Message(message="AURORA Voice listo.", details=status)


@router.post("/query", response_model=VoiceResponse, summary="Consultar por texto transcrito")
def voice_query(
    payload: VoiceQuery,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> VoiceResponse:
    reply = answer(db, payload.text, user, provider=settings.voice_provider)
    return VoiceResponse(
        intent=reply.intent,
        confidence=reply.confidence,
        answer=reply.answer,
        provider=settings.voice_provider,
        data=reply.data,
        suggestions=reply.suggestions,
    )
