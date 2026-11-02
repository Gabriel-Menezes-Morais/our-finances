"""Owner can recover paused AI entirely through confirmed Telegram commands."""

import asyncio
from pathlib import Path

from app.agent.orchestrator import Orchestrator
from app.config import Settings
from app.db import Database
from app.domain import FinanceService
from app.jobs.store import DurableStore


def test_pause_and_resume_all_remains_available_without_ai(tmp_path: Path) -> None:
    database = Database("sqlite:///:memory:")
    database.initialize()
    service = FinanceService(database, 123)
    store = DurableStore(database)
    agent = Orchestrator(
        Settings(_env_file=None, telegram_owner_user_id=123, report_directory=tmp_path),
        service,
        store,
    )
    pause = asyncio.run(agent.handle("/pausar tudo", actor_id=123, chat_id=123, event_id="pause"))
    assert pause.confirmation_token
    agent.confirm(pause.confirmation_token, 123, 123)
    assert all(service.snapshot()["operations"].values())
    resume = asyncio.run(
        agent.handle("/retomar tudo", actor_id=123, chat_id=123, event_id="resume")
    )
    assert resume.confirmation_token
    agent.confirm(resume.confirmation_token, 123, 123)
    assert not any(service.snapshot()["operations"].values())
