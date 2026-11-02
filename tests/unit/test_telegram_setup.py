"""Pareamento e autorização sem fazer chamadas Telegram reais."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message

from app.telegram.bot import OwnerOnly
from app.telegram.setup import is_pairing_message


def message(text: str, user_id: int = 123, chat_type: str = "private") -> Message:
    return Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": user_id, "type": chat_type, "title": "test"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "text": text,
        }
    )


def test_only_exact_private_pairing_challenge_is_valid() -> None:
    assert is_pairing_message(message("/start one-time-challenge"), "one-time-challenge")
    assert not is_pairing_message(message("/start"), "one-time-challenge")
    assert not is_pairing_message(message("/start other-value"), "one-time-challenge")
    assert not is_pairing_message(message("olá, teste"), "one-time-challenge")
    assert not is_pairing_message(
        message("/start one-time-challenge", chat_type="group"), "one-time-challenge"
    )


@pytest.mark.parametrize(
    ("user_id", "chat_type", "allowed"),
    [(123, "private", True), (456, "private", False), (123, "group", False)],
)
def test_owner_middleware_rejects_other_users_and_groups(
    user_id: int, chat_type: str, allowed: bool
) -> None:
    handler = AsyncMock(return_value="allowed")
    result = asyncio.run(OwnerOnly(123)(handler, message("/status", user_id, chat_type), {}))
    assert handler.await_count == int(allowed)
    assert result == ("allowed" if allowed else None)
