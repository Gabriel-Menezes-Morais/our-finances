"""Contratos reais dos clientes, com HTTP simulado e credenciais fictícias."""

import asyncio
import json
from dataclasses import asdict

import httpx
import pytest
from pydantic import SecretStr

from app.ai.llm import probe_openai
from app.audio.elevenlabs import probe_elevenlabs, transcribe_audio
from app.config import Settings
from app.providers import ProviderFailure, failure_reason


def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_mode="offline",
        openai_model="gpt-6-luna",
        openai_api_key=SecretStr("fake-openai-test"),
        elevenlabs_api_key=SecretStr("fake-elevenlabs-test"),
        telegram_bot_token=None,
        telegram_owner_user_id=None,
    )


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, None, "authentication_failed"),
        (403, None, "permission_denied"),
        (404, None, "resource_or_model_unavailable"),
        (429, "insufficient_quota", "insufficient_quota"),
        (429, "rate_limit_exceeded", "rate_limit_exceeded"),
        (429, "unknown-private-message", "rate_or_quota_limit"),
        (500, None, "provider_request_failed"),
    ],
)
def test_failure_reasons_are_controlled(status: int, code: str | None, expected: str) -> None:
    assert failure_reason(status, code) == expected


def test_openai_model_check_precedes_inference() -> None:
    called: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(
                200, json={"id": "gpt-6-luna", "object": "model", "created": 0, "owned_by": "test"}
            )
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-6-luna"
        assert payload["store"] is False
        assert not any(k in payload for k in ("max_tokens", "max_completion_tokens", "maxTokens"))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-6-luna",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "OUR_FINANCES_OK", "annotations": []}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 3,
                    "total_tokens": 8,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    result = asyncio.run(probe_openai(settings(), client))
    assert result.ok
    assert result.input_tokens == 5
    assert called == ["/v1/models/gpt-6-luna", "/v1/responses"]


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_openai_does_not_fallback_or_retry(status: int) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            json={"error": {"message": "fake-openai-test", "code": "model_not_found"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    result = asyncio.run(probe_openai(settings(), client))
    assert not result.ok
    assert calls == 1
    assert "fake-openai-test" not in json.dumps(asdict(result))


def test_elevenlabs_transcribes_using_its_own_api() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.elevenlabs.io"
        assert request.url.path == "/v1/speech-to-text"
        assert request.headers["xi-api-key"] == "fake-elevenlabs-test"
        assert b"scribe_v2" in request.content
        return httpx.Response(200, json={"text": "Gastei vinte reais."})

    async def run() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await transcribe_audio(settings(), b"test audio", "test.wav", client=client)

    assert asyncio.run(run()) == "Gastei vinte reais."


def test_openai_quota_message_without_error_code_is_classified_safely() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "You exceeded your current quota; fake-openai-test",
                    "code": None,
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    result = asyncio.run(probe_openai(settings(), client))
    assert result.reason == "insufficient_quota"
    assert "fake-openai-test" not in json.dumps(asdict(result))


@pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": 20}, []])
def test_invalid_transcript_is_not_success(payload: object) -> None:
    async def run() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ProviderFailure):
                await transcribe_audio(settings(), b"test", "test.wav", client=client)

    asyncio.run(run())


def test_elevenlabs_error_does_not_expose_provider_body() -> None:
    async def run() -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(401, json={"detail": "fake-elevenlabs-test"})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            result = await probe_elevenlabs(settings(), b"test", client=client)
            assert not result.ok
            assert result.reason == "authentication_failed"
            assert "fake-elevenlabs-test" not in json.dumps(asdict(result))

    asyncio.run(run())


def test_empty_audio_does_not_call_api() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        pytest.fail("Empty audio must not call the provider")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ProviderFailure, match="empty_audio"):
                await transcribe_audio(settings(), b"", "test.wav", client=client)

    asyncio.run(run())
