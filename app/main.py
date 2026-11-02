"""Local/PaaS entry point with health, durable webhook and optional polling."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import uvicorn
from aiogram import Bot
from aiogram.types import BotCommand, Update
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from app.config import Settings
from app.observability import event
from app.runtime import Runtime


def create_app(settings: Settings | None = None, *, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task[Any]] = []
        owned_bot = None
        current = runtime
        if current is None:
            if settings.telegram_bot_token and settings.app_mode == "connected":
                owned_bot = Bot(token=settings.telegram_bot_token.get_secret_value())
            current = Runtime(settings, bot=owned_bot)
        app.state.runtime = current
        if settings.run_worker_in_app:
            tasks.append(asyncio.create_task(current.worker(), name="durable-worker"))
        if settings.app_mode == "connected" and settings.telegram_transport == "polling":
            tasks.append(asyncio.create_task(current.poll(), name="telegram-polling"))
        if current.bot and settings.app_mode == "connected":
            await current.bot.set_my_commands(
                [
                    BotCommand(command="start", description="Começar e ver ajuda"),
                    BotCommand(command="resumo", description="Resumo financeiro do mês"),
                    BotCommand(command="lancamentos", description="Consultar lançamentos"),
                    BotCommand(command="categorias", description="Consultar categorias"),
                    BotCommand(command="limites", description="Consultar limites de gastos"),
                    BotCommand(command="metas", description="Consultar metas"),
                    BotCommand(command="grafico", description="Gráfico do mês"),
                    BotCommand(
                        command="exportar", description="Exportar planilha local XLSX ou CSV"
                    ),
                    BotCommand(
                        command="desfazer", description="Prévia para desfazer última alteração"
                    ),
                    BotCommand(command="status", description="Estado do banco, filas e conexões"),
                    BotCommand(command="ajuda", description="Ver exemplos de uso"),
                ]
            )
        app.state.tasks = tasks
        try:
            yield
        finally:
            current.running = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if owned_bot:
                await owned_bot.session.close()
            if runtime is None:
                current.close()

    app = FastAPI(title="Our Finances", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def request_event(request: Request, call_next: Any) -> Any:
        started = time.monotonic()
        correlation_id = str(uuid4())
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            event(
                "http",
                "completed" if status_code < 500 else "failed",
                correlation_id=correlation_id,
                status_code=status_code,
                duration_ms=round((time.monotonic() - started) * 1000),
            )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "our-finances"}

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        current = request.app.state.runtime
        if not current.database.health():
            raise HTTPException(503, "database_unavailable")
        if any(task.done() for task in request.app.state.tasks):
            raise HTTPException(503, "background_process_stopped")
        return {"status": "ready"}

    @app.post("/telegram/webhook")
    async def webhook(request: Request) -> dict[str, bool]:
        if settings.telegram_transport != "webhook" or settings.app_mode != "connected":
            raise HTTPException(404, "not_enabled")
        expected = settings.telegram_webhook_secret
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if expected is None or not hmac.compare_digest(
            expected.get_secret_value().encode(), supplied.encode()
        ):
            raise HTTPException(403, "forbidden")
        raw = await request.body()
        if len(raw) > 256 * 1024:
            raise HTTPException(413, "payload_too_large")
        try:
            update = Update.model_validate_json(raw)
        except ValidationError:
            raise HTTPException(400, "invalid_update") from None
        # HTTP 200 is returned only after durable ingress. Unauthorized input
        # receives an empty acknowledgement without writing private data.
        request.app.state.runtime.ingest(update)
        return {"ok": True}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Our Finances local ou PaaS.")
    parser.add_argument("--connected", action="store_true", help="Autoriza as APIs configuradas.")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        settings = Settings(app_mode="connected") if args.connected else Settings()
        uvicorn.run(
            create_app(settings),
            host=args.host,
            port=settings.port,
            access_log=False,
            log_level="critical",
        )
    except KeyboardInterrupt:
        return
    except Exception as exc:
        event("application", "failed", reason=type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
