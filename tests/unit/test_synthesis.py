"""TTS simulado conserva texto e exige escolha explícita de voz/modelo."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.audio.elevenlabs import synthesize_audio
from app.config import Settings
from app.providers import ProviderFailure


def settings(**values: object) -> Settings:
    return Settings(
        _env_file=None,
        elevenlabs_api_key=SecretStr("fictional-key"),
        elevenlabs_voice_id="fictional-voice",
        elevenlabs_tts_model="fictional-model",
    ).model_copy(update=values)


def test_tts_sends_exact_text_to_chosen_voice() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/text-to-speech/owner-choice"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert json.loads(request.content) == {
            "text": "R$ 12,34; saldo desconhecido.",
            "model_id": "fictional-model",
        }
        return httpx.Response(200, content=b"ID3-fictional", headers={"content-type": "audio/mpeg"})

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await synthesize_audio(
                settings(),
                "R$ 12,34; saldo desconhecido.",
                voice_id="owner-choice",
                client=client,
            )

    assert asyncio.run(run()) == b"ID3-fictional"


@pytest.mark.parametrize(
    "values,reason",
    [
        ({"elevenlabs_voice_id": None}, "voice_selection_required"),
        ({"elevenlabs_tts_model": None}, "tts_model_selection_required"),
        ({"elevenlabs_api_key": None}, "missing_api_key"),
    ],
)
def test_missing_choice_never_calls_provider(values: dict[str, object], reason: str) -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("Missing configuration must not reach provider")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            with pytest.raises(ProviderFailure, match=reason):
                await synthesize_audio(settings(**values), "Texto", client=client)

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,content_type,content",
    [
        (401, "application/json", b'{"private":"secret"}'),
        (200, "application/json", b'{"private":"secret"}'),
        (200, "audio/mpeg", b""),
    ],
)
def test_failed_or_non_audio_response_is_safe(
    status: int, content_type: str, content: bytes
) -> None:
    async def run() -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                status,
                content=content,
                headers={"content-type": content_type},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ProviderFailure) as error:
                await synthesize_audio(settings(), "Texto", client=client)
            assert "private" not in str(error.value) and "secret" not in str(error.value)

    asyncio.run(run())
