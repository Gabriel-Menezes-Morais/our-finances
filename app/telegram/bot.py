"""Owner-only Telegram bot with durable ingress and local financial processing."""

import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, TelegramObject

from app.config import Settings


class OwnerOnly(BaseMiddleware):
    def __init__(self, owner_id: int) -> None:
        self.owner_id = owner_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if (
            not isinstance(event, Message)
            or event.chat.type != "private"
            or event.from_user is None
            or event.from_user.is_bot
            or event.from_user.id != self.owner_id
            or event.chat.id != self.owner_id
        ):
            return None
        return await handler(event, data)


async def run(settings: Settings) -> int:
    from app.runtime import Runtime

    logging.disable(logging.CRITICAL)
    if settings.telegram_bot_token is None or settings.telegram_owner_user_id is None:
        print("Cadastre token e vincule a conta com python -m app.telegram.setup.")
        return 2
    async with Bot(token=settings.telegram_bot_token.get_secret_value()) as bot:
        if (await bot.get_webhook_info()).url:
            print("Webhook ativo: polling não iniciado para evitar conflito.")
            return 2
        runtime = Runtime(settings, bot=bot)
        worker = asyncio.create_task(runtime.worker())
        print("BOT_RUNNING: acesso restrito, banco local e confirmações ativos.", flush=True)
        try:
            await runtime.poll()
        finally:
            runtime.running = False
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            runtime.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot local de finanças.")
    parser.add_argument("--connected", action="store_true", help="Ativa as APIs já configuradas.")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        settings = Settings(app_mode="connected") if args.connected else Settings()
        code = asyncio.run(run(settings))
    except KeyboardInterrupt:
        code = 0
    except Exception:
        print("Bot interrompido; confira configuração. Credenciais ocultas.")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
