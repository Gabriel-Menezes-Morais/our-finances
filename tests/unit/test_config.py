"""Verifica isolamento, validação e proteção de credenciais sem chaves reais."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

SETTING_NAMES = (
    "APP_MODE",
    "APP_TIMEZONE",
    "BASE_CURRENCY",
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_STT_MODEL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_USER_ID",
)


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(Settings.model_config, "env_file", tmp_path / ".env")
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_offline_needs_no_credentials() -> None:
    settings = Settings()
    assert settings.app_mode == "offline"
    assert settings.openai_api_key is None
    assert settings.elevenlabs_api_key is None
    assert settings.telegram_bot_token is None
    assert settings.telegram_owner_user_id is None


def test_connected_rejects_missing_credentials() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(app_mode="connected")
    for name in ("OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_USER_ID"):
        assert name in str(error.value)


def test_connected_text_does_not_require_audio_key() -> None:
    settings = Settings(
        app_mode="connected",
        openai_api_key="fake-openai-value",  # type: ignore[arg-type]
        telegram_bot_token="fake-telegram-value",  # type: ignore[arg-type]
        telegram_owner_user_id=123,
    )
    assert settings.elevenlabs_api_key is None


@pytest.mark.parametrize("name", ["openai_api_key", "elevenlabs_api_key", "telegram_bot_token"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_secret_is_absent(name: str, value: str) -> None:
    settings = Settings(**{name: value})
    assert getattr(settings, name) is None


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_owner_is_absent(value: str) -> None:
    settings = Settings(telegram_owner_user_id=value)  # type: ignore[arg-type]
    assert settings.telegram_owner_user_id is None


@pytest.mark.parametrize("owner", [0, -1, "@someone"])
def test_owner_must_be_positive_numeric_id(owner: object) -> None:
    with pytest.raises(ValidationError):
        Settings(telegram_owner_user_id=owner)  # type: ignore[arg-type]


def test_secret_values_are_hidden_in_repr_and_json() -> None:
    value = "only-a-fake-fixture-value"
    settings = Settings(
        openai_api_key=value,  # type: ignore[arg-type]
        elevenlabs_api_key=value,  # type: ignore[arg-type]
        telegram_bot_token=value,  # type: ignore[arg-type]
    )
    assert value not in repr(settings)
    assert value not in settings.model_dump_json()


def test_secret_values_are_hidden_in_error_text() -> None:
    value = "fake-value-that-must-not-leak"
    with pytest.raises(ValidationError) as error:
        Settings(app_mode="connected", openai_api_key=value)  # type: ignore[arg-type]
    assert value not in str(error.value)


def test_model_cannot_be_silently_replaced() -> None:
    with pytest.raises(ValidationError):
        Settings(openai_model="different-model")  # type: ignore[arg-type]


def test_invalid_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="fuso IANA"):
        Settings(app_timezone="Not/A-Timezone")


def test_local_env_is_loaded_and_secrets_are_trimmed(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        'OPENAI_API_KEY="  fake-local-value  "\nTELEGRAM_OWNER_USER_ID=123\n',
        encoding="utf-8",
    )
    settings = Settings()
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "fake-local-value"
    assert settings.telegram_owner_user_id == 123


def test_environment_overrides_local_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TELEGRAM_OWNER_USER_ID=123\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_OWNER_USER_ID", "456")
    assert Settings().telegram_owner_user_id == 456


def test_unrelated_working_directory_env_is_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = tmp_path / "unrelated-directory"
    child.mkdir()
    (child / ".env").write_text("OPENAI_API_KEY=fake-unrelated-value\n", encoding="utf-8")
    monkeypatch.chdir(child)
    assert Settings().openai_api_key is None


def test_unknown_future_env_variables_do_not_break_bootstrap(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FUTURE_TEST_VARIABLE=not-a-secret\n", encoding="utf-8")
    assert Settings().app_mode == "offline"
