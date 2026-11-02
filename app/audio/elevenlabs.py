"""Integração STT ElevenLabs com erros seguros e sem logar áudio ou texto."""

from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.providers import ProbeResult, ProviderFailure, failure_reason

TRANSCRIPTION_ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"
SPEECH_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech"


async def synthesize_audio(
    settings: Settings,
    text: str,
    *,
    voice_id: str | None = None,
    client: httpx.AsyncClient,
) -> bytes:
    """Produz MP3 usando modelo configurado e voz escolhida pelo proprietário.

    Contrato: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
    A ausência de escolha mantém o fluxo de texto utilizável pelo chamador.
    """
    if settings.elevenlabs_api_key is None:
        raise ProviderFailure("missing_api_key")
    selected_voice = voice_id or settings.elevenlabs_voice_id
    if not selected_voice:
        raise ProviderFailure("voice_selection_required")
    if not settings.elevenlabs_tts_model:
        raise ProviderFailure("tts_model_selection_required")
    if not text.strip():
        raise ProviderFailure("empty_text")
    if len(text) > 6000:
        raise ProviderFailure("text_too_large")
    try:
        response = await client.post(
            f"{SPEECH_ENDPOINT}/{quote(selected_voice, safe='')}",
            headers={
                "xi-api-key": settings.elevenlabs_api_key.get_secret_value(),
                "accept": "audio/mpeg",
            },
            params={"output_format": "mp3_44100_128"},
            json={"text": text, "model_id": settings.elevenlabs_tts_model},
            timeout=60.0,
        )
    except httpx.TimeoutException:
        raise ProviderFailure("timeout") from None
    except httpx.RequestError:
        raise ProviderFailure("connection_failed") from None
    if not response.is_success:
        raise ProviderFailure(failure_reason(response.status_code), response.status_code)
    if (
        not response.content
        or response.headers.get("content-type", "").split(";", 1)[0] != "audio/mpeg"
        or len(response.content) > 16 * 1024 * 1024
    ):
        raise ProviderFailure("invalid_provider_response")
    return response.content


async def transcribe_audio(
    settings: Settings,
    audio: bytes,
    filename: str,
    *,
    client: httpx.AsyncClient,
) -> str:
    if settings.elevenlabs_api_key is None:
        raise ProviderFailure("missing_api_key")
    if not audio:
        raise ProviderFailure("empty_audio")
    if len(audio) > 8 * 1024 * 1024:
        raise ProviderFailure("audio_too_large")
    try:
        response = await client.post(
            TRANSCRIPTION_ENDPOINT,
            headers={"xi-api-key": settings.elevenlabs_api_key.get_secret_value()},
            data={"model_id": settings.elevenlabs_stt_model, "diarize": "false"},
            files={"file": (Path(filename).name, audio)},
            timeout=60.0,
        )
    except httpx.TimeoutException:
        raise ProviderFailure("timeout") from None
    except httpx.RequestError:
        raise ProviderFailure("connection_failed") from None

    if not response.is_success:
        raise ProviderFailure(failure_reason(response.status_code), response.status_code)
    try:
        payload: Any = response.json()
    except ValueError:
        raise ProviderFailure("invalid_provider_response") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise ProviderFailure("invalid_provider_response")
    text = str(payload["text"]).strip()
    if not text:
        raise ProviderFailure("empty_transcript")
    return text


async def probe_elevenlabs(
    settings: Settings, audio: bytes, *, client: httpx.AsyncClient
) -> ProbeResult:
    try:
        await transcribe_audio(settings, audio, "probe.wav", client=client)
        return ProbeResult("elevenlabs", True, "transcription", "nonempty_transcript", 200)
    except ProviderFailure as exc:
        return ProbeResult("elevenlabs", False, "transcription", exc.reason, exc.status_code)
