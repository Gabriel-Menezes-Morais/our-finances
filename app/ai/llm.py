"""Único módulo autorizado a importar o SDK e chamar a OpenAI."""

import asyncio
import base64
import json
from collections.abc import Mapping, Sequence

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from openai.types.responses import ResponseInputContentParam, ResponseInputParam
from pydantic import ValidationError

from app.agent.contracts import ConversationTurn, ImageInput, Interpretation, ModelUsage
from app.agent.prompts import INTERPRET_INSTRUCTIONS
from app.config import Settings
from app.providers import ProbeResult, ProviderFailure, failure_reason

_INTERPRET_CONCURRENCY = asyncio.Semaphore(2)


async def interpret(
    settings: Settings,
    text: str,
    context: Mapping[str, object],
    history: Sequence[ConversationTurn] = (),
    *,
    images: Sequence[ImageInput] = (),
    http_client: httpx.AsyncClient | None = None,
) -> Interpretation:
    """Interpreta sem executar: sessão, autorização e mutações pertencem ao chamador.

    Histórico e contexto são enviados como dados em uma mensagem de usuário. A
    mensagem de política é local e não pode ser substituída por roles recebidas.
    O transporte injetável permite testar o contrato sem chamadas pagas.
    """
    if settings.openai_api_key is None:
        raise ProviderFailure("missing_api_key")
    if not text.strip() and not images:
        raise ProviderFailure("empty_input")
    if len(text) > 12000 or len(history) > 16 or len(images) > 4:
        raise ProviderFailure("context_too_large")
    try:
        data = json.dumps(
            {
                "context": dict(context),
                "history": [turn.model_dump() for turn in history],
                "request": text,
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    except (ValueError, TypeError):
        raise ProviderFailure("invalid_context") from None
    if len(data.encode("utf-8")) > 128000:
        raise ProviderFailure("context_too_large")
    content: list[ResponseInputContentParam] = [{"type": "input_text", "text": data}]
    for image in images:
        if not image.data:
            raise ProviderFailure("empty_image")
        encoded = base64.b64encode(image.data).decode("ascii")
        content.append(
            {
                "type": "input_image",
                "detail": "auto",
                "image_url": f"data:{image.mime_type};base64,{encoded}",
            }
        )
    request_input: ResponseInputParam = [{"role": "user", "content": content}]
    try:
        async with (
            _INTERPRET_CONCURRENCY,
            AsyncOpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                timeout=45.0,
                max_retries=0,
                http_client=http_client,
            ) as client,
        ):
            response = await client.responses.parse(
                model=settings.openai_model,
                instructions=INTERPRET_INSTRUCTIONS,
                input=request_input,
                text_format=Interpretation,
                store=False,
            )
        if response.model != settings.openai_model:
            raise ProviderFailure("unexpected_model")
        if response.status != "completed":
            raise ProviderFailure("incomplete_response")
        result = response.output_parsed
        if result is None:
            refused = any(
                item.type == "message" and any(c.type == "refusal" for c in item.content)
                for item in response.output
            )
            raise ProviderFailure("model_refusal" if refused else "invalid_model_output")
        if response.usage:
            result = result.with_usage(
                ModelUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.total_tokens,
                )
            )
        return result
    except APIStatusError as exc:
        raise ProviderFailure(classify_api_error(exc), exc.status_code) from None
    except APITimeoutError:
        raise ProviderFailure("timeout") from None
    except APIConnectionError:
        raise ProviderFailure("connection_failed") from None
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise ProviderFailure("invalid_model_output") from None


def classify_api_error(error: APIStatusError) -> str:
    reason = failure_reason(error.status_code, error.code)
    if error.status_code != 429 or reason != "rate_or_quota_limit":
        return reason
    # O corpo fica somente em memória; nenhum texto do provedor vai para os logs.
    body = json.dumps(error.body, default=lambda _: "").lower()
    if any(
        term in body
        for term in ("insufficient_quota", "exceeded your current quota", "no balance left")
    ):
        return "insufficient_quota"
    if any(
        term in body
        for term in (
            "rate_limit_exceeded",
            "rate limit reached",
            "requests per minute",
            "tokens per minute",
        )
    ):
        return "rate_limit_exceeded"
    return reason


async def probe_openai(
    settings: Settings, http_client: httpx.AsyncClient | None = None
) -> ProbeResult:
    """Valida acesso ao modelo exato antes de uma inferência mínima autorizada."""
    if settings.openai_api_key is None:
        return ProbeResult("openai", False, "credentials", "missing_api_key")

    stage = "model_access"
    try:
        async with AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=30.0,
            max_retries=0,
            http_client=http_client,
        ) as client:
            model = await client.models.retrieve(settings.openai_model)
            if model.id != settings.openai_model:
                return ProbeResult("openai", False, stage, "unexpected_model")
            stage = "inference"
            response = await client.responses.create(
                model=settings.openai_model,
                input="Responda apenas OUR_FINANCES_OK.",
                store=False,
            )
            expected = response.output_text.strip() == "OUR_FINANCES_OK"
            usage = response.usage
            return ProbeResult(
                "openai",
                expected,
                stage,
                "verified" if expected else "unexpected_probe_response",
                status_code=200,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
            )
    except APIStatusError as exc:
        return ProbeResult("openai", False, stage, classify_api_error(exc), exc.status_code)
    except APITimeoutError:
        return ProbeResult("openai", False, stage, "timeout")
    except APIConnectionError:
        return ProbeResult("openai", False, stage, "connection_failed")
