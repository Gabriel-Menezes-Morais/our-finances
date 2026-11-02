"""Inbox/reinício e entrega Telegram com DB real e APIs externas proibidas."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from aiogram import Bot
from aiogram.types import Update
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.agent.contracts import ActionPayload, Interpretation, ProposedAction, QueryRequest
from app.agent.orchestrator import Reply
from app.config import Settings
from app.db import Database
from app.jobs.scheduler import Scheduler
from app.main import create_app
from app.models import InboundEvent, OutboxJob, PendingAction
from app.runtime import Runtime
from app.telegram.delivery import deliver


class RecordingBot:
    id = 987654

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def set_my_commands(self, *_: object, **__: object) -> None:
        pass

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.messages.append({"chat_id": chat_id, "text": text, **kwargs})

    async def answer_callback_query(self, *_: object, **__: object) -> None:
        pass


def incoming(update_id: int, *, owner: int = 123, chat: int = 123, text: str = "/resumo") -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 1793620800,
                "from": {"id": owner, "is_bot": False, "first_name": "Fictício"},
                "chat": {"id": chat, "type": "private" if chat > 0 else "group"},
                "text": text,
            },
        }
    )


def callback(update_id: int, token: str, *, owner: int = 123, chat: int = 123) -> Update:
    message = incoming(update_id, owner=owner, chat=chat).message
    assert message is not None
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": "callback-" + str(update_id),
                "chat_instance": "fictional",
                "from": {"id": owner, "is_bot": False, "first_name": "Fictício"},
                "data": "confirm:" + token,
                "message": message.model_dump(mode="json"),
            },
        }
    )


def runtime_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_mode="connected",
        telegram_owner_user_id=123,
        telegram_bot_token=SecretStr("123456:fictional-test-token"),
        openai_api_key=SecretStr("fictional-test-key"),
        database_url=SecretStr(f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}"),
        report_directory=tmp_path / "exports",
        telegram_transport="webhook",
        telegram_webhook_secret=SecretStr("fictional-webhook-secret"),
        run_worker_in_app=False,
    )


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Runtime]:
    async def forbid_network(*_: object, **__: object) -> None:
        pytest.fail("Unexpected external request in runtime integration test")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbid_network)
    bot = RecordingBot()
    settings = runtime_settings(tmp_path)
    database = Database(settings.database_url.get_secret_value())
    current = Runtime(settings, database=database, bot=cast(Bot, bot))
    yield current
    current.close()


def fake_proposal() -> Interpretation:
    return Interpretation(
        answer="Prévia",
        explanation="Compra fictícia",
        needs_clarification=False,
        actions=[
            ProposedAction(
                operation="create_transaction",
                payload=ActionPayload(
                    type="expense",
                    amount_minor=1899,
                    currency="BRL",
                    occurrence_date="2026-11-02",
                ),
            )
        ],
    )


def test_unknown_sender_group_and_stolen_callback_never_enter_inbox(runtime: Runtime) -> None:
    assert not runtime.ingest(incoming(1, owner=456, chat=456))
    assert not runtime.ingest(incoming(2, owner=123, chat=-100))
    assert not runtime.ingest(callback(3, "stolen", owner=456))
    assert not runtime.ingest(callback(4, "stolen", owner=123, chat=-100))
    with runtime.database.session() as session:
        assert session.scalar(select(func.count()).select_from(InboundEvent)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxJob)) == 0


def test_duplicate_source_and_restart_yield_one_confirmable_financial_fact(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def interpret_fake(*_: Any, **__: Any) -> Interpretation:
        nonlocal calls
        calls += 1
        return fake_proposal()

    monkeypatch.setattr("app.agent.orchestrator.interpret", interpret_fake)
    update = incoming(10, text="Gastei R$ 18,99 hoje")
    assert runtime.ingest(update) and runtime.ingest(update)
    row = runtime.store.pending_inbounds("telegram:987654")[0]
    asyncio.run(runtime.process_inbound(row["id"]))
    asyncio.run(runtime.process_inbound(row["id"]))
    assert calls == 1 and not runtime.service.snapshot()["transactions"]
    with runtime.database.session() as session:
        pending = session.scalar(select(PendingAction))
        assert pending is not None
        token = pending.id
        assert session.scalar(select(func.count()).select_from(InboundEvent)) == 1
    restarted = Runtime(runtime.settings, database=runtime.database, bot=runtime.bot)
    assert restarted.ingest(callback(11, token))
    new = restarted.store.pending_inbounds("telegram:987654")[0]
    asyncio.run(restarted.process_inbound(new["id"]))
    assert restarted.ingest(callback(12, token))
    replay = restarted.store.pending_inbounds("telegram:987654")[0]
    asyncio.run(restarted.process_inbound(replay["id"]))
    snapshot = restarted.service.snapshot()
    assert len(snapshot["transactions"]) == 1
    assert sum(item["amount_minor"] for item in snapshot["transactions"]) == 1899


def test_orphaned_durable_inbox_is_recovered_after_restart(runtime: Runtime) -> None:
    row = runtime.store.persist_inbound(
        "telegram:987654",
        "20",
        123,
        incoming(20).model_dump(mode="json"),
    )
    restarted = Runtime(runtime.settings, database=runtime.database, bot=runtime.bot)
    restarted.recover()
    assert restarted.store.get_job_by_key("inbound:" + row["id"]) is not None
    asyncio.run(restarted.process_inbound(row["id"]))
    recovered = restarted.store.get_inbound(row["id"])
    assert recovered is not None and recovered["status"] == "processed"
    assert restarted.store.get_job_by_key("reply:" + row["id"]) is not None


def test_webhook_requires_secret_and_ack_is_after_durable_ingress(runtime: Runtime) -> None:
    app = create_app(runtime.settings, runtime=runtime)
    data = incoming(30).model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post("/telegram/webhook", json=data).status_code == 403
        with runtime.database.session() as session:
            assert session.scalar(select(func.count()).select_from(InboundEvent)) == 0
        response = client.post(
            "/telegram/webhook",
            json=data,
            headers={"X-Telegram-Bot-Api-Secret-Token": "fictional-webhook-secret"},
        )
        assert response.status_code == 200
        with runtime.database.session() as session:
            assert session.scalar(select(func.count()).select_from(InboundEvent)) == 1
            assert session.scalar(select(func.count()).select_from(OutboxJob)) == 1


def test_delivery_rejects_other_recipient_and_files_outside_exports(
    runtime: Runtime,
    tmp_path: Path,
) -> None:
    bot = cast(RecordingBot, runtime.bot)
    with pytest.raises(PermissionError):
        asyncio.run(
            deliver(cast(Bot, bot), 123, 456, Reply("Private"), runtime.settings.report_directory)
        )
    assert not bot.messages
    outside = tmp_path / "other-private.csv"
    outside.write_text("never deliver", encoding="utf-8")
    with pytest.raises(PermissionError):
        asyncio.run(
            deliver(
                cast(Bot, bot),
                123,
                123,
                Reply("Arquivo", files=[outside]),
                runtime.settings.report_directory,
            )
        )


def test_callback_handler_rechecks_actual_private_chat(runtime: Runtime) -> None:
    token = runtime.orchestrator.propose(
        fake_proposal().to_operations(),
        123,
        123,
    ).confirmation_token
    assert token
    group_callback = callback(40, token, chat=-100).callback_query
    assert group_callback
    with pytest.raises(PermissionError):
        asyncio.run(runtime.handle_callback(group_callback))
    assert runtime.service.snapshot()["transactions"] == []


def test_followup_export_failure_preserves_confirmed_financial_fact(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = runtime.orchestrator.propose(
        fake_proposal().to_operations(),
        123,
        123,
        query=QueryRequest(kind="export", format="csv"),
    ).confirmation_token
    assert token

    async def fail_export(*_: Any, **__: Any) -> Reply:
        raise OSError("simulated local export failure")

    monkeypatch.setattr(runtime.orchestrator, "answer_query", fail_export)
    assert runtime.ingest(callback(50, token))
    row = runtime.store.pending_inbounds("telegram:987654")[0]
    asyncio.run(runtime.process_inbound(row["id"]))
    snapshot = runtime.service.snapshot()
    assert len(snapshot["transactions"]) == 1
    assert snapshot["transactions"][0]["amount_minor"] == 1899
    reply_job = runtime.store.get_job_by_key("reply:" + row["id"])
    assert reply_job is not None
    assert "não repita o lançamento" in reply_job["payload"]["text"]


def test_crash_after_reply_enqueue_replays_without_second_llm_call(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def interpreted(*_: Any, **__: Any) -> Interpretation:
        nonlocal calls
        calls += 1
        return fake_proposal()

    monkeypatch.setattr("app.agent.orchestrator.interpret", interpreted)
    assert runtime.ingest(incoming(60, text="Compra fictícia"))
    row = runtime.store.pending_inbounds("telegram:987654")[0]
    mark = runtime.store.mark_inbound

    def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("simulated loss after outbox commit")

    monkeypatch.setattr(runtime.store, "mark_inbound", crash)
    with pytest.raises(RuntimeError):
        asyncio.run(runtime.process_inbound(row["id"]))
    assert runtime.store.get_job_by_key("reply:" + row["id"])
    monkeypatch.setattr(runtime.store, "mark_inbound", mark)
    asyncio.run(runtime.process_inbound(row["id"]))
    assert calls == 1
    with runtime.database.session() as session:
        assert session.scalar(select(func.count()).select_from(PendingAction)) == 1


def test_offline_app_never_constructs_bot_or_calls_provider(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_bot(*_: Any, **__: Any) -> Bot:
        pytest.fail("Offline startup must not construct the provider client")

    monkeypatch.setattr("app.main.Bot", forbidden_bot)
    offline = runtime.settings.model_copy(update={"app_mode": "offline"})
    with TestClient(create_app(offline)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert (
            client.post("/telegram/webhook", json=incoming(70).model_dump(mode="json")).status_code
            == 404
        )


def test_scheduler_fault_does_not_stop_other_durable_jobs(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processed = False

    def fail_schedule(*_: Any, **__: Any) -> int:
        raise ValueError("simulated invalid calendar in one stored schedule")

    async def process_other_job() -> bool:
        nonlocal processed
        processed = True
        runtime.running = False
        return True

    monkeypatch.setattr(Scheduler, "tick", fail_schedule)
    monkeypatch.setattr(runtime, "run_one_job", process_other_job)
    asyncio.run(runtime.worker())
    assert processed
