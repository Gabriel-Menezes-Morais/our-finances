"""Standalone worker for a separate PaaS service; no polling consumer."""

import asyncio
import logging

from aiogram import Bot

from app.config import Settings
from app.observability import event
from app.runtime import Runtime


async def run() -> None:
    settings = Settings()
    if settings.app_mode != "connected" or settings.telegram_bot_token is None:
        raise ValueError("Worker conectado exige APP_MODE=connected e token configurado.")
    async with Bot(token=settings.telegram_bot_token.get_secret_value()) as bot:
        runtime = Runtime(settings, bot=bot)
        try:
            await runtime.worker()
        finally:
            runtime.close()


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return
    except Exception as exc:
        event("worker", "failed", reason=type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
