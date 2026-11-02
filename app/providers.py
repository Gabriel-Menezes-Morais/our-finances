"""Resultados e erros seguros, sem corpos de resposta nem credenciais."""

from dataclasses import dataclass


class ProviderFailure(Exception):
    """Erro público com motivo controlado, seguro para exibir no terminal."""

    def __init__(self, reason: str, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


def failure_reason(status: int, provider_code: str | None = None) -> str:
    if status == 429 and provider_code in {"insufficient_quota", "rate_limit_exceeded"}:
        return provider_code
    return {
        401: "authentication_failed",
        403: "permission_denied",
        404: "resource_or_model_unavailable",
        429: "rate_or_quota_limit",
    }.get(status, "provider_request_failed")


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    ok: bool
    stage: str
    reason: str
    status_code: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
