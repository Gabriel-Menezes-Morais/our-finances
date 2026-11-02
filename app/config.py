"""Configuração local sem chamadas de rede ou leitura de projetos vizinhos."""

from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, PositiveInt, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Carrega somente o .env deste projeto e variáveis conhecidas.

    Segredos são mascarados em repr/JSON e inputs não aparecem no texto dos
    erros. Consumidores não devem registrar ValidationError.errors() com inputs.
    Instanciar a configuração não verifica chaves nem autoriza chamadas reais.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
        frozen=True,
    )

    app_mode: Literal["offline", "connected"] = "offline"
    app_timezone: str = "America/Sao_Paulo"
    base_currency: Literal["BRL"] = "BRL"
    # ID verificado em 02/11/2026: developers.openai.com/api/docs/models/gpt-6-luna
    openai_model: Literal["gpt-6-luna"] = "gpt-6-luna"
    openai_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    # ID verificado na documentação ElevenLabs em 02/11/2026; acesso depende da chave.
    elevenlabs_stt_model: str = "scribe_v2"
    telegram_bot_token: SecretStr | None = None
    telegram_owner_user_id: PositiveInt | None = None
    database_url: SecretStr = Field(
        default_factory=lambda: SecretStr(
            "sqlite+pysqlite:///" + (PROJECT_ROOT / "data" / "our_finances.sqlite3").as_posix()
        )
    )
    report_directory: Path = PROJECT_ROOT / "exports"
    elevenlabs_tts_model: str | None = None
    elevenlabs_voice_id: str | None = None
    telegram_webhook_secret: SecretStr | None = None
    max_input_characters: int = Field(default=8000, ge=100, le=32000)
    max_audio_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=8 * 1024 * 1024)
    max_audio_seconds: int = Field(default=180, ge=1, le=600)
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    confirmation_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    telegram_transport: Literal["polling", "webhook", "disabled"] = "polling"
    run_worker_in_app: bool = True
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator(
        "openai_api_key",
        "elevenlabs_api_key",
        "telegram_bot_token",
        "telegram_owner_user_id",
        mode="before",
    )
    @classmethod
    def normalize_blank_values(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("APP_TIMEZONE deve ser um fuso IANA válido.") from exc
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_driver(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return "postgresql+psycopg://" + value[len("postgres://") :]
            if value.startswith("postgresql://"):
                return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @model_validator(mode="after")
    def require_connected_credentials(self) -> Self:
        if self.app_mode == "offline":
            return self

        required = {
            "OPENAI_API_KEY": self.openai_api_key,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_OWNER_USER_ID": self.telegram_owner_user_id,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError("Modo conectado exige: " + ", ".join(missing) + ".")
        # ElevenLabs só é exigido pela futura integração de áudio; texto é independente.
        return self
