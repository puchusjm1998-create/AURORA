"""Voz neuronal: selección, caché, endpoint y errores de configuración."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import tts


@pytest.fixture()
def edge_settings(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_tts_provider", "edge")
    monkeypatch.setattr(settings, "voice_tts_voice", "es-ES-ElviraNeural")
    monkeypatch.setattr(settings, "voice_tts_cache_dir", tmp_path / "voice")
    monkeypatch.setattr(settings, "voice_tts_max_chars", 1200)
    return settings


def test_edge_synthesis_and_cache(edge_settings, monkeypatch):
    calls = {"count": 0}

    def fake_edge(text: str, voice: str, rate: str) -> bytes:
        calls["count"] += 1
        assert text == "Hola, AURORA."
        assert voice == "es-ES-ElviraNeural"
        return b"ID3" + b"fake-mp3" * 10

    monkeypatch.setattr(tts, "_synthesize_edge", fake_edge)
    audio, meta = tts.synthesize("  Hola,   AURORA.  ")
    assert audio.startswith(b"ID3")
    assert meta["cached"] is False
    assert calls["count"] == 1

    cached, meta2 = tts.synthesize("Hola, AURORA.")
    assert cached == audio
    assert meta2["cached"] is True
    assert calls["count"] == 1


def test_browser_provider_does_not_fake_audio(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_tts_provider", "browser")
    with pytest.raises(Exception) as exc:
        tts.synthesize("Hola")
    assert getattr(exc.value, "code", None) == "tts_browser_only"


def test_speak_endpoint_returns_audio_and_status(admin_client, edge_settings, monkeypatch):
    def fake_edge(text: str, voice: str, rate: str) -> bytes:
        return b"ID3" + b"x" * 128

    monkeypatch.setattr(tts, "_synthesize_edge", fake_edge)
    status = admin_client.get("/api/v1/voice/status")
    assert status.status_code == 200, status.text
    tts_status = status.json()["details"]["tts"]
    assert tts_status["provider"] == "edge"
    assert tts_status["neural"] is True
    assert tts_status["available"] is True

    response = admin_client.post(
        "/api/v1/voice/speak", json={"text": "Consulta de stock", "rate": "+0%"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["x-voice-provider"] == "edge"
    assert response.content.startswith(b"ID3")

    second = admin_client.post("/api/v1/voice/speak", json={"text": "Consulta de stock"})
    assert second.status_code == 200
    assert second.headers["x-voice-cached"] == "1"


def test_piper_missing_model_is_not_configured(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_tts_provider", "piper")
    monkeypatch.setattr(settings, "voice_tts_model_path", tmp_path / "missing.onnx")
    status = tts.status()
    assert status["neural"] is True
    assert status["available"] is False
    assert status["audio_leaves_device"] is False
    with pytest.raises(Exception) as exc:
        tts.synthesize("Hola")
    assert getattr(exc.value, "code", None) == "tts_not_configured"


def test_rate_scale_follows_speech_synthesis_percentages():
    assert tts._rate_scale("+0%") == 1.0
    assert tts._rate_scale("+100%") == pytest.approx(0.5)
    assert tts._rate_scale("-50%") == pytest.approx(2.0)
    assert tts._rate_scale("") == 1.0


def test_piper_endpoint_returns_wav(admin_client, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_tts_provider", "piper")
    monkeypatch.setattr(settings, "voice_tts_cache_dir", tmp_path / "voice")
    monkeypatch.setattr(
        tts, "_synthesize_piper", lambda text, rate: b"RIFF" + b"w" * 128
    )
    status = admin_client.get("/api/v1/voice/status")
    assert status.status_code == 200
    assert status.json()["details"]["tts"]["provider"] == "piper"
    response = admin_client.post(
        "/api/v1/voice/speak", json={"text": "Stock del muelle"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["x-voice-provider"] == "piper"
    assert response.content.startswith(b"RIFF")


def test_openai_without_key_is_not_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_tts_provider", "openai")
    monkeypatch.setattr(settings, "voice_tts_api_key", "")
    with pytest.raises(Exception) as exc:
        tts.synthesize("Hola")
    assert getattr(exc.value, "code", None) == "tts_not_configured"
