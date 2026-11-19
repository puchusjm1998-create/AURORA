"""Síntesis de voz neuronal del servidor.

Proveedores:
- ``piper``: voz neuronal local en ONNX (sin red ni clave; motor piper-tts).
- ``edge``: voces neuronales de Microsoft Edge (sin clave; requiere salida a Internet).
- ``openai``: endpoint compatible con ``/v1/audio/speech`` (requiere clave).
- ``browser``: no genera audio en el servidor; el frontend usa SpeechSynthesis.

El audio se cachea en disco por hash del texto, voz y proveedor. No se guarda
texto libre en nombres de archivo ni en logs.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import threading
import wave
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import AppError

PROVIDERS = {"browser", "piper", "edge", "openai"}
_PIPER_VOICES: dict[str, Any] = {}
_PIPER_LOCK = threading.Lock()


def _settings():
    return get_settings()


def _provider() -> str:
    provider = _settings().voice_tts_provider.strip().lower()
    return provider if provider in PROVIDERS else "browser"


def _clean_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        raise AppError("El texto está vacío.", status_code=422, code="empty_text")
    limit = max(100, _settings().voice_tts_max_chars)
    if len(cleaned) > limit:
        raise AppError(
            f"El texto supera el límite de {limit} caracteres.",
            status_code=422,
            code="text_too_long",
            details={"max_chars": limit},
        )
    return cleaned


def _cache_suffix(provider: str) -> str:
    return ".wav" if provider == "piper" else ".mp3"


def _cache_path(
    text: str, voice: str, rate: str, provider: str
) -> Path:
    identity = provider
    if provider == "piper":
        model = Path(_settings().voice_tts_model_path)
        try:
            identity += f"|{model.name}|{int(model.stat().st_mtime)}"
        except OSError:
            identity += f"|{model.name}|missing"
    digest = hashlib.sha256(
        f"{identity}|{voice}|{rate}|{text}".encode("utf-8")
    ).hexdigest()
    return (
        Path(_settings().voice_tts_cache_dir)
        / digest[:2]
        / f"{digest}{_cache_suffix(provider)}"
    )


def _rate_scale(rate: str) -> float:
    """Convierte el rate de SpeechSynthesis (+20 %, -10 %) en length_scale."""
    match = re.fullmatch(r"\s*([+-]?\d{1,3})\s*%?\s*", rate or "+0%")
    percent = int(match.group(1)) if match else 0
    percent = max(-50, min(100, percent))
    return 1.0 / (1.0 + percent / 100.0)


def _load_piper(model_path: Path) -> Any:
    key = str(model_path)
    with _PIPER_LOCK:
        voice = _PIPER_VOICES.get(key)
        if voice is None:
            try:
                from piper import PiperVoice, SynthesisConfig
            except ImportError as exc:  # pragma: no cover - depende del despliegue
                raise AppError(
                    "El motor Piper no está instalado.",
                    status_code=503,
                    code="tts_not_configured",
                ) from exc
            voice = PiperVoice.load(key)
            _PIPER_VOICES[key] = (voice, SynthesisConfig)
        return _PIPER_VOICES[key]


def _synthesize_piper(text: str, rate: str) -> bytes:
    settings = _settings()
    model_path = Path(settings.voice_tts_model_path)
    if not model_path.is_file():
        raise AppError(
            "Falta el modelo de voz local; configure VOICE_TTS_MODEL_PATH.",
            status_code=503,
            code="tts_not_configured",
            details={"model_path": str(model_path)},
        )
    try:
        voice, synthesis_config = _load_piper(model_path)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            voice.synthesize_wav(
                text, wav, syn_config=synthesis_config(length_scale=_rate_scale(rate))
            )
        audio = buffer.getvalue()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - modelo corrupto o ONNX no disponible
        raise AppError(
            "El motor de voz local no pudo sintetizar el texto.",
            status_code=502,
            code="tts_provider_error",
            details={"error": str(exc)[:300]},
        ) from exc
    if not audio:
        raise AppError(
            "El motor local devolvió audio vacío.",
            status_code=502,
            code="tts_empty_audio",
        )
    return audio


def _synthesize_edge(text: str, voice: str, rate: str) -> bytes:
    try:
        import edge_tts
    except ImportError as exc:  # pragma: no cover - depende del despliegue
        raise AppError(
            "El proveedor Edge TTS no está instalado.",
            status_code=503,
            code="tts_not_configured",
        ) from exc

    async def collect() -> bytes:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        chunks = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.extend(chunk["data"])
        return bytes(chunks)

    try:
        audio = asyncio.run(collect())
    except Exception as exc:  # noqa: BLE001 - red, cuota o voz inexistente
        raise AppError(
            "El proveedor de voz neuronal no respondió.",
            status_code=502,
            code="tts_provider_error",
            details={"error": str(exc)[:300]},
        ) from exc
    if not audio:
        raise AppError(
            "El proveedor devolvió audio vacío.",
            status_code=502,
            code="tts_empty_audio",
        )
    return audio


def _synthesize_openai(text: str, voice: str) -> bytes:
    settings = _settings()
    if not settings.voice_tts_api_key.strip():
        raise AppError(
            "Falta VOICE_TTS_API_KEY para el proveedor OpenAI.",
            status_code=503,
            code="tts_not_configured",
        )
    base = settings.voice_tts_base_url.rstrip("/")
    url = f"{base}/audio/speech" if base.endswith("/v1") else f"{base}/v1/audio/speech"
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.voice_tts_api_key.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.voice_tts_model,
                "voice": voice,
                "input": text,
                "response_format": "mp3",
            },
            timeout=settings.voice_tts_timeout,
        )
    except httpx.HTTPError as exc:
        raise AppError(
            "No se pudo contactar con el proveedor de voz neuronal.",
            status_code=502,
            code="tts_provider_error",
            details={"error": str(exc)[:300]},
        ) from exc
    if response.status_code >= 400:
        raise AppError(
            "El proveedor de voz neuronal rechazó la petición.",
            status_code=502,
            code="tts_provider_error",
            details={"status": response.status_code, "body": response.text[:300]},
        )
    if not response.content:
        raise AppError(
            "El proveedor devolvió audio vacío.",
            status_code=502,
            code="tts_empty_audio",
        )
    return response.content


def status() -> dict[str, Any]:
    settings = _settings()
    provider = _provider()
    model_path = Path(settings.voice_tts_model_path)
    model_present = model_path.is_file() and model_path.with_suffix(
        ".onnx.json"
    ).is_file()
    available = (
        (provider == "piper" and model_present)
        or provider == "edge"
        or (provider == "openai" and bool(settings.voice_tts_api_key.strip()))
    )
    reason = ""
    if provider == "piper" and not model_present:
        reason = (
            "Falta el modelo ONNX; descárguelo y configure VOICE_TTS_MODEL_PATH."
        )
    elif provider == "browser":
        reason = "La síntesis se hace en el navegador con SpeechSynthesis."
    elif provider == "piper":
        reason = "Piper sintetiza en el servidor con una voz neuronal ONNX local; el audio no sale del servidor."
    elif provider == "edge":
        reason = "Edge TTS usa las voces neuronales de Microsoft; requiere salida a Internet."
    elif not settings.voice_tts_api_key.strip():
        reason = "Configure VOICE_TTS_API_KEY para activar OpenAI TTS."
    return {
        "provider": provider,
        "available": available,
        "neural": provider in {"piper", "edge", "openai"},
        "voice": settings.voice_tts_voice,
        "model": (
            model_path.name
            if provider == "piper"
            else settings.voice_tts_model if provider == "openai" else None
        ),
        "audio_leaves_device": provider in {"edge", "openai"},
        "reason": reason,
    }


def synthesize(
    text: str, *, voice: str | None = None, rate: str = "+0%"
) -> tuple[bytes, dict[str, Any]]:
    settings = _settings()
    provider = _provider()
    if provider == "browser":
        raise AppError(
            "La voz neuronal no está configurada; use SpeechSynthesis en el navegador.",
            status_code=409,
            code="tts_browser_only",
        )
    cleaned = _clean_text(text)
    selected_voice = (voice or settings.voice_tts_voice).strip()
    if not selected_voice:
        raise AppError(
            "Indique una voz válida.", status_code=422, code="invalid_voice"
        )
    cache = _cache_path(cleaned, selected_voice, rate, provider)
    if cache.is_file() and cache.stat().st_size > 0:
        return cache.read_bytes(), {
            "provider": provider,
            "voice": selected_voice,
            "cached": True,
            "bytes": cache.stat().st_size,
            "media_type": "audio/wav" if provider == "piper" else "audio/mpeg",
        }

    if provider == "piper":
        audio = _synthesize_piper(cleaned, rate)
    elif provider == "edge":
        audio = _synthesize_edge(cleaned, selected_voice, rate)
    else:
        audio = _synthesize_openai(cleaned, selected_voice)

    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_name(f".{cache.name}.part")
    temp.write_bytes(audio)
    temp.replace(cache)
    return audio, {
        "provider": provider,
        "voice": selected_voice,
        "cached": False,
        "bytes": len(audio),
        "media_type": "audio/wav" if provider == "piper" else "audio/mpeg",
    }
