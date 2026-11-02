"""Queued exports survive a stateless PaaS restart without financial re-execution."""

import asyncio
from pathlib import Path
from typing import Any, cast

from aiogram import Bot
from aiogram.types import FSInputFile

from app.agent.orchestrator import Reply
from app.config import Settings
from app.db import Database
from app.runtime import Runtime


class AttachmentBot:
    id = 987654

    def __init__(self) -> None:
        self.documents: list[bytes] = []

    async def send_message(self, *_: Any, **__: Any) -> None:
        pass

    async def send_document(self, chat: int, document: FSInputFile) -> None:
        assert chat == 123
        self.documents.append(Path(document.path).read_bytes())


def test_queued_attachment_is_restored_after_original_file_disappears(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_mode="offline",
        telegram_owner_user_id=123,
        report_directory=tmp_path / "exports",
    )
    database = Database("sqlite:///:memory:")
    fake = AttachmentBot()
    runtime = Runtime(settings, database=database, bot=cast(Bot, fake))
    source = settings.report_directory / "snapshot-r0.csv"
    payload = b"type,amount_minor\nexpense,12345\n"
    source.write_bytes(payload)
    runtime.enqueue_reply(Reply("Exportação local, revisão 0", files=[source]), "fixture-export")
    source.unlink()
    assert asyncio.run(runtime.run_one_job())
    assert fake.documents == [payload]
    assert not asyncio.run(runtime.run_one_job())
    assert runtime.service.snapshot()["transactions"] == []
    runtime.close()
