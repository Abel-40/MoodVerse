"""Speech-to-text providers.

Mirrors AIProvider and EmbeddingProvider: one interface the pipeline depends
on, swapping providers means adding a class, never touching the caller. Runs
inside a Celery task (see app/services/reflection_pipeline.py), so
`transcribe` is a plain sync call, not async.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings, get_settings


class SpeechToTextProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, content_type: str | None) -> str:
        """Return the canonical text for one audio clip. Raises on failure -
        never returns a guess dressed up as a transcript."""


class CartesiaSpeechToTextProvider(SpeechToTextProvider):
    """Batch transcription via Cartesia's Ink Whisper model (POST /stt).

    Implemented against Cartesia's documented batch STT endpoint: multipart
    upload with `file` + `model`, `X-API-Key` and `Cartesia-Version` headers,
    a `{"text": ...}` JSON response. Base URL, model and API version are all
    settings rather than constants, since this was implemented without a live
    Cartesia account to test against - if their contract has moved on, these
    can be corrected from the environment with no code change.
    """

    name = "cartesia"

    _EXTENSION_BY_CONTENT_TYPE = {
        "audio/flac": "flac",
        "audio/m4a": "m4a",
        "audio/mp4": "mp4",
        "audio/mpeg": "mp3",
        "audio/mpga": "mpga",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/webm": "webm",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.cartesia_api_key:
            raise RuntimeError(
                "CARTESIA_API_KEY is not set. Set it in the environment or the "
                "backend .env to use voice reflections."
            )

    def transcribe(self, audio_bytes: bytes, content_type: str | None) -> str:
        extension = self._EXTENSION_BY_CONTENT_TYPE.get((content_type or "").lower(), "webm")
        files = {
            "file": (f"audio.{extension}", audio_bytes, content_type or "application/octet-stream")
        }
        data = {"model": self._settings.cartesia_stt_model}

        try:
            response = httpx.post(
                f"{self._settings.cartesia_base_url}/stt",
                headers={
                    "X-API-Key": self._settings.cartesia_api_key or "",
                    "Cartesia-Version": self._settings.cartesia_api_version,
                },
                data=data,
                files=files,
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Cartesia transcription request failed: {exc}") from exc

        if response.status_code >= 400:
            raise RuntimeError(
                f"Cartesia transcription failed: {response.status_code} {response.text[:500]}"
            )

        body = response.json()
        text = body.get("text")
        if not text:
            raise RuntimeError("Cartesia returned no transcript text.")
        return text


def get_speech_to_text_provider(settings: Settings | None = None) -> SpeechToTextProvider:
    """Resolve the configured provider. The only place a provider is chosen."""
    settings = settings or get_settings()
    if settings.stt_provider == "cartesia":
        return CartesiaSpeechToTextProvider(settings)
    raise ValueError(f"unknown STT_PROVIDER {settings.stt_provider!r}")
