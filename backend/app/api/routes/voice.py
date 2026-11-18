"""Consultas de voz: el navegador transcribe; el servidor responde con datos reales."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.models import User
from app.schemas import Message, VoiceQuery, VoiceResponse, VoiceSpeakRequest
from app.services import tts
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
    status["tts"] = tts.status()
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


@router.post(
    "/speak",
    summary="Sintetizar una respuesta con voz neuronal",
    response_class=Response,
    responses={
        200: {
            "content": {
                "audio/wav": {},
                "audio/mpeg": {},
            }
        }
    },
)
def voice_speak(
    payload: VoiceSpeakRequest,
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> Response:
    audio, meta = tts.synthesize(payload.text, voice=payload.voice, rate=payload.rate)
    return Response(
        content=audio,
        media_type=str(meta.get("media_type", "audio/mpeg")),
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Voice-Provider": str(meta["provider"]),
            "X-Voice-Name": str(meta["voice"]),
            "X-Voice-Cached": "1" if meta["cached"] else "0",
            "X-Voice-Bytes": str(meta["bytes"]),
        },
    )
