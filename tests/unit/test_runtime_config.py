"""Deployment URL normalization and display don't expose or alter financial values."""

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.formatting import format_money


@pytest.mark.parametrize("prefix", ["postgres://", "postgresql://", "postgresql+psycopg://"])
def test_paas_postgres_uses_installed_driver_and_masks_password(prefix: str) -> None:
    settings = Settings(
        _env_file=None,
        app_mode="offline",
        database_url=SecretStr(prefix + "fixture:fake-password@localhost/test"),
    )
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert "fake-password" not in repr(settings)
    assert "fake-password" not in settings.model_dump_json()


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (1234, "BRL", "BRL 12,34"),
        (123456789, "BRL", "BRL 1.234.567,89"),
        (-25, "BRL", "BRL -0,25"),
        (1200, "JPY", "JPY 1.200"),
        (1234, "KWD", "KWD 1,234"),
    ],
)
def test_currency_display_preserves_minor_unit_precision(
    amount: int,
    currency: str,
    expected: str,
) -> None:
    assert format_money(amount, currency) == expected
