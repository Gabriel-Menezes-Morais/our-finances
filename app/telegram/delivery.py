"""Deliver only locally generated artifacts to the explicitly paired owner."""

from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.agent.orchestrator import Reply


async def deliver(bot: Bot, owner_id: int, chat_id: int, reply: Reply, report_root: Path) -> None:
    if chat_id != owner_id:
        raise PermissionError("Destino não autorizado.")
    markup = None
    if reply.confirmation_token:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Confirmar", callback_data="confirm:" + reply.confirmation_token
                    ),
                    InlineKeyboardButton(
                        text="Cancelar", callback_data="cancel:" + reply.confirmation_token
                    ),
                ]
            ]
        )
    text = reply.text or "Pedido processado."
    chunks = [text[index : index + 3500] for index in range(0, len(text), 3500)]
    for index, chunk in enumerate(chunks):
        await bot.send_message(
            chat_id,
            chunk,
            reply_markup=markup if index == len(chunks) - 1 else None,
            parse_mode=None,
        )
    for artifact in reply.files:
        artifact = artifact.resolve()
        if (
            not artifact.is_relative_to(report_root.resolve())
            or not artifact.is_file()
            or artifact.stat().st_size > 40 * 1024 * 1024
        ):
            raise PermissionError("Arquivo fora do diretório de exportações ou inválido.")
        if artifact.suffix.lower() == ".png":
            await bot.send_photo(chat_id, FSInputFile(artifact))
        elif artifact.suffix.lower() == ".mp3":
            await bot.send_audio(chat_id, FSInputFile(artifact), title="Resumo Our Finances")
        else:
            await bot.send_document(chat_id, FSInputFile(artifact))
