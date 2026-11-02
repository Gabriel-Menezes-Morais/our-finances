"""Pareamento explícito do proprietário, sem cadastro aberto de administradores."""

import argparse
import asyncio
import hmac
import secrets
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message
from dotenv import set_key
from pydantic import ValidationError

from app.config import PROJECT_ROOT, Settings


def is_pairing_message(message: Message, challenge: str) -> bool:
    return bool(
        message.chat.type == "private"
        and message.from_user
        and not message.from_user.is_bot
        and message.chat.id == message.from_user.id
        and message.text
        and hmac.compare_digest(
            message.text.encode("utf-8"), ("/start " + challenge).encode("utf-8")
        )
    )


def save_owner(owner_id: int, destination: Path = PROJECT_ROOT / ".env") -> None:
    if owner_id <= 0 or destination.is_symlink():
        raise ValueError("Destino ou identidade inválidos.")
    if destination.resolve().parent != PROJECT_ROOT.resolve():
        raise ValueError("Destino fora do projeto.")
    set_key(str(destination), "TELEGRAM_OWNER_USER_ID", str(owner_id), quote_mode="always")


async def pair(settings: Settings) -> int:
    if settings.telegram_bot_token is None:
        print("Cadastre TELEGRAM_BOT_TOKEN no .env local; não envie o token ao chat.")
        return 2
    if settings.telegram_owner_user_id is not None:
        print("Proprietário já vinculado. Nenhuma identidade foi substituída.")
        return 0

    async with Bot(token=settings.telegram_bot_token.get_secret_value()) as bot:
        me = await bot.get_me()
        webhook = await bot.get_webhook_info()
        if webhook.url:
            print("Bot tem webhook ativo; o pareamento não alterou a configuração existente.")
            return 2
        if not me.username:
            print("O bot ainda não possui username para criar o link de pareamento.")
            return 2
        challenge = secrets.token_urlsafe(24)
        print(f"PAIRING_URL=https://t.me/{me.username}?start={challenge}", flush=True)
        print("Abra o link e toque em Iniciar em até 5 minutos.", flush=True)
        deadline = time.monotonic() + 300
        offset: int | None = None
        while time.monotonic() < deadline:
            updates = await bot.get_updates(offset=offset, timeout=20, allowed_updates=["message"])
            for update in updates:
                offset = update.update_id + 1
                message = update.message
                if not message or not is_pairing_message(message, challenge):
                    continue
                assert message.from_user is not None
                save_owner(message.from_user.id)
                # Confirma recebimento somente após persistir a identidade autorizada.
                await bot.get_updates(offset=offset, timeout=0, allowed_updates=["message"])
                await message.answer(
                    "Sua conta foi vinculada ao Our Finances. "
                    "A preparação do bot foi concluída; os registros financeiros ainda "
                    "estão em implementação."
                )
                print("PAIRING_COMPLETE: proprietário salvo localmente; credenciais ocultas.")
                return 0
        print("PAIRING_EXPIRED: execute novamente para gerar outro link.")
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Vincula a conta do proprietário ao bot.")
    parser.add_argument(
        "--start", action="store_true", help="Inicia o bot após concluir o vínculo."
    )
    args = parser.parse_args()

    async def connect() -> int:
        result = await pair(Settings())
        if result == 0 and args.start:
            from app.telegram.bot import run

            return await run(Settings())
        return result

    try:
        code = asyncio.run(connect())
    except KeyboardInterrupt:
        print("Preparação interrompida.")
        code = 0
    except ValidationError:
        print("Configuração inválida; confira o .env sem compartilhar seus valores.")
        code = 2
    except Exception as exc:
        print(
            f"Pareamento não concluído ({type(exc).__name__}); "
            "verifique acesso ao bot. Credenciais não exibidas."
        )
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
