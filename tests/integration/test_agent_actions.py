"""Propostas fictícias atravessam confirmação e domínio real, sem rede."""

import asyncio
import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.agent.contracts import (
    ActionPayload,
    Allocation,
    Interpretation,
    ProposedAction,
    QueryFilters,
    QueryRequest,
)
from app.agent.orchestrator import Orchestrator
from app.config import Settings
from app.db import Database
from app.domain import FinanceService
from app.jobs.store import DurableStore
from app.models import AppliedCommand, AuditEvent


@pytest.fixture
def agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Orchestrator]:
    async def forbid_network(*_: object, **__: object) -> None:
        pytest.fail("Integration fixture must never send an external request")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbid_network)
    database = Database(f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    database.initialize()
    service = FinanceService(database, 123)
    settings = Settings(_env_file=None, report_directory=tmp_path / "exports")
    yield Orchestrator(settings, service, DurableStore(database))
    database.close()


def proposed_expense(amount: int = 1234) -> Interpretation:
    return Interpretation(
        answer="Proposta fictícia.",
        explanation="Conferir antes de salvar.",
        needs_clarification=False,
        actions=[
            ProposedAction(
                operation="create_transaction",
                payload=ActionPayload(
                    type="expense",
                    amount_minor=amount,
                    currency="BRL",
                    occurrence_date="2026-11-02",
                    description="Mercado fictício",
                ),
            )
        ],
    )


def test_confirmation_applies_ledger_once_even_after_replay(agent: Orchestrator) -> None:
    reply = asyncio.run(agent.apply_interpretation(proposed_expense(), 123, 123))
    assert agent.service.snapshot()["transactions"] == []
    token = reply.confirmation_token
    assert token
    agent.confirm(token, 123, 123)
    agent.confirm(token, 123, 123)
    snapshot = agent.service.snapshot()
    assert len(snapshot["transactions"]) == 1
    assert sum(row["amount_minor"] for row in snapshot["transactions"]) == 1234
    with agent.service.database.session() as session:
        assert session.scalar(select(func.count()).select_from(AppliedCommand)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_financial_preview_explains_split_with_names_and_money(agent: Orchestrator) -> None:
    category = agent.service.execute(
        "create_category", {"name": "Mercado"}, idempotency_key="preview-category"
    )["id"]
    reply = agent.propose(
        [
            {
                "operation": "create_transaction",
                "payload": {
                    "type": "expense",
                    "amount_minor": 1234,
                    "currency": "BRL",
                    "occurrence_date": "2026-11-02",
                    "allocations": [{"category_id": category, "amount_minor": 1234}],
                },
            }
        ],
        123,
        123,
    )
    assert "Criar lançamento" in reply.text
    assert "Categoria: Mercado" in reply.text and "BRL 12,34" in reply.text
    assert "amount_minor" not in reply.text and str(category) not in reply.text
    assert agent.service.snapshot()["transactions"] == []


def test_correction_preview_uses_original_currency_and_is_preserved(agent: Orchestrator) -> None:
    transaction = agent.service.execute(
        "create_transaction",
        {
            "type": "expense",
            "amount_minor": 1234,
            "currency": "JPY",
            "occurrence_date": "2026-11-02",
            "description": "Transporte fictício",
        },
        idempotency_key="preview-yen",
    )["id"]
    reply = agent.propose(
        [
            {
                "operation": "update_transaction",
                "payload": {
                    "id": transaction,
                    "amount_minor": 2345,
                },
            }
        ],
        123,
        123,
    )
    assert "JPY 2.345" in reply.text and "BRL" not in reply.text
    assert "Transporte fictício" in reply.text
    assert reply.confirmation_token
    confirmed = agent.confirm(reply.confirmation_token, 123, 123)
    assert "salva no banco" in confirmed.text and "JPY 2.345" in confirmed.text
    agent.service.execute(
        "update_transaction",
        {"id": transaction, "description": "Outro nome"},
        idempotency_key="later-edit",
    )
    replayed = agent.confirm(reply.confirmation_token, 123, 123)
    assert "Transporte fictício" in replayed.text and "Outro nome" not in replayed.text
    assert agent.service.snapshot()["transactions"][0]["amount_minor"] == 2345


def test_confirmation_and_cancellation_survive_new_orchestrator(agent: Orchestrator) -> None:
    reply = asyncio.run(agent.apply_interpretation(proposed_expense(), 123, 123))
    token = reply.confirmation_token
    assert token
    restarted = Orchestrator(
        agent.settings, FinanceService(agent.service.database, 123), agent.store
    )
    restarted.confirm(token, 123, 123, cancel=True)
    restarted.confirm(token, 123, 123)
    assert restarted.service.snapshot()["transactions"] == []


def test_stolen_confirmation_and_group_chat_cannot_write(agent: Orchestrator) -> None:
    token = asyncio.run(agent.apply_interpretation(proposed_expense(), 123, 123)).confirmation_token
    assert token
    for actor_id, chat_id in [(456, 123), (123, -100), (456, 456)]:
        with pytest.raises(PermissionError):
            agent.confirm(token, actor_id, chat_id)
    assert not agent.service.snapshot()["transactions"]
    agent.confirm(token, 123, 123)
    assert len(agent.service.snapshot()["transactions"]) == 1


def test_stale_preview_is_rejected_without_partial_mutations(agent: Orchestrator) -> None:
    token = asyncio.run(agent.apply_interpretation(proposed_expense(), 123, 123)).confirmation_token
    assert token
    agent.service.execute("create_tag", {"name": "Outra alteração"}, idempotency_key="other")
    revision = agent.service.snapshot()["revision"]
    agent.confirm(token, 123, 123)
    assert agent.service.snapshot()["revision"] == revision
    assert agent.service.snapshot()["transactions"] == []


def test_invalid_member_of_batch_rolls_back_every_effect(agent: Orchestrator) -> None:
    interpretation = proposed_expense()
    interpretation.actions.insert(
        0,
        ProposedAction(
            operation="create_area",
            payload=ActionPayload(name="Casa fictícia"),
        ),
    )
    interpretation.actions[-1].payload.amount_minor = -1
    token = asyncio.run(agent.apply_interpretation(interpretation, 123, 123)).confirmation_token
    assert token
    agent.confirm(token, 123, 123)
    snapshot = agent.service.snapshot()
    assert snapshot["areas"] == [] and snapshot["transactions"] == []
    assert snapshot["revision"] == 0


def test_two_legitimate_equal_purchases_are_not_deduplicated(agent: Orchestrator) -> None:
    for _ in range(2):
        token = asyncio.run(
            agent.apply_interpretation(proposed_expense(), 123, 123)
        ).confirmation_token
        assert token
        agent.confirm(token, 123, 123)
    assert len(agent.service.snapshot()["transactions"]) == 2
    assert sum(row["amount_minor"] for row in agent.service.snapshot()["transactions"]) == 2468


def test_clarification_never_creates_a_pending_mutation(agent: Orchestrator) -> None:
    reply = asyncio.run(
        agent.apply_interpretation(
            Interpretation(
                answer="",
                explanation="Valor ausente",
                question="Qual valor?",
                needs_clarification=True,
                actions=[],
            ),
            123,
            123,
        )
    )
    assert not reply.confirmation_token
    assert not agent.service.snapshot()["transactions"]


def seed_report_transactions(agent: Orchestrator) -> tuple[str, str]:
    first = agent.service.execute(
        "create_category",
        {"name": "Mercado"},
        idempotency_key="category-first",
    )["id"]
    second = agent.service.execute(
        "create_category",
        {"name": "Lazer"},
        idempotency_key="category-second",
    )["id"]
    for category, amount, day in [
        (first, 1111, "2026-11-01"),
        (second, 2222, "2026-11-02"),
        (first, 9000, "2026-12-01"),
    ]:
        agent.service.execute(
            "create_transaction",
            {
                "type": "expense",
                "amount_minor": amount,
                "occurrence_date": day,
                "allocations": [{"category_id": category, "amount_minor": amount}],
            },
            idempotency_key="seed:" + str(amount),
        )
    return first, second


def test_filtered_export_has_exact_facts_and_no_next_month_leak(agent: Orchestrator) -> None:
    first, _ = seed_report_transactions(agent)
    query = QueryRequest(
        kind="export",
        format="csv",
        filters=QueryFilters(
            category_id=first,
            start_date="2026-11-01",
            end_date="2026-12-01",
            basis="accrual",
        ),
    )
    reply = asyncio.run(agent.answer_query(query))
    assert len(reply.files) == 1
    with reply.files[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [int(row["expense_minor"]) for row in rows] == [1111]
    assert {row["category_id"] for row in rows} == {first}
    assert len(agent.service.snapshot()["transactions"]) == 3


def test_plural_filtered_transaction_list_omits_unrelated_facts(agent: Orchestrator) -> None:
    first, _ = seed_report_transactions(agent)
    reply = asyncio.run(
        agent.answer_query(
            QueryRequest(
                kind="list",
                entity="transactions",
                filters=QueryFilters(
                    category_ids=[first],
                    start_date="2026-11-01",
                    end_date="2026-12-01",
                ),
            )
        )
    )
    assert "1111" in reply.text
    assert "2222" not in reply.text and "9000" not in reply.text


def test_text_ingress_denies_foreign_actor_before_llm(
    agent: Orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden(*_: Any, **__: Any) -> Interpretation:
        pytest.fail("Unauthorized input reached AI")

    monkeypatch.setattr("app.agent.orchestrator.interpret", forbidden)
    with pytest.raises(PermissionError):
        asyncio.run(
            agent.handle("registre 10 reais", actor_id=456, chat_id=456, event_id="foreign")
        )
    assert not agent.service.snapshot()["transactions"]


def test_area_category_and_purchase_are_one_atomic_confirmed_journey(agent: Orchestrator) -> None:
    interpretation = Interpretation(
        answer="Prévia",
        explanation="Organizar e registrar a compra",
        needs_clarification=False,
        actions=[
            ProposedAction(operation="create_area", payload=ActionPayload(name="Casa")),
            ProposedAction(
                operation="create_category",
                payload=ActionPayload(
                    name="Mercado",
                    type="expense",
                    area_id="$0",
                ),
            ),
            ProposedAction(
                operation="create_transaction",
                payload=ActionPayload(
                    type="expense",
                    amount_minor=10001,
                    occurrence_date="2026-11-02",
                    allocations=[Allocation(amount_minor=10001, category_id="$1")],
                ),
            ),
        ],
    )
    token = asyncio.run(agent.apply_interpretation(interpretation, 123, 123)).confirmation_token
    assert token
    assert not agent.service.snapshot()["areas"]
    agent.confirm(token, 123, 123)
    snapshot = agent.service.snapshot()
    assert (
        len(snapshot["areas"]) == len(snapshot["categories"]) == len(snapshot["transactions"]) == 1
    )
    assert snapshot["categories"][0]["area_id"] == snapshot["areas"][0]["id"]
    assert snapshot["allocations"][0]["category_id"] == snapshot["categories"][0]["id"]
    assert snapshot["transactions"][0]["amount_minor"] == 10001


def test_crash_after_financial_commit_does_not_repeat_purchase(
    agent: Orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = asyncio.run(agent.apply_interpretation(proposed_expense(), 123, 123)).confirmation_token
    assert token
    resolve = agent.store.resolve_pending

    def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("simulated process loss after ledger commit")

    monkeypatch.setattr(agent.store, "resolve_pending", crash)
    with pytest.raises(RuntimeError):
        agent.confirm(token, 123, 123)
    assert len(agent.service.snapshot()["transactions"]) == 1
    monkeypatch.setattr(agent.store, "resolve_pending", resolve)
    agent.confirm(token, 123, 123)
    assert sum(row["amount_minor"] for row in agent.service.snapshot()["transactions"]) == 1234
    with agent.service.database.session() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_correcting_categorized_purchase_adjusts_amount_and_preserves_identity(
    agent: Orchestrator,
) -> None:
    category = agent.service.execute(
        "create_category",
        {"name": "Mercado"},
        idempotency_key="category-for-correction",
    )["id"]
    original = agent.service.execute(
        "create_transaction",
        {
            "type": "expense",
            "amount_minor": 1234,
            "occurrence_date": "2026-11-02",
            "allocations": [{"category_id": category, "amount_minor": 1234}],
        },
        idempotency_key="categorized-purchase",
    )["id"]
    interpretation = Interpretation(
        answer="Prévia",
        explanation="Corrigir para R$ 25,00",
        needs_clarification=False,
        actions=[
            ProposedAction(
                operation="update_transaction",
                payload=ActionPayload(
                    id=original,
                    amount_minor=2500,
                ),
            )
        ],
    )
    token = asyncio.run(agent.apply_interpretation(interpretation, 123, 123)).confirmation_token
    assert token
    agent.confirm(token, 123, 123)
    snapshot = agent.service.snapshot()
    assert len(snapshot["transactions"]) == 1
    assert snapshot["transactions"][0]["id"] == original
    assert snapshot["transactions"][0]["amount_minor"] == 2500
    assert snapshot["allocations"][0]["category_id"] == category
    assert snapshot["allocations"][0]["amount_minor"] == 2500


def test_saved_analysis_runs_with_persisted_filters_and_domain_metadata(
    agent: Orchestrator,
) -> None:
    category, _ = seed_report_transactions(agent)
    interpretation = Interpretation(
        answer="Prévia",
        explanation="Salvar análise",
        needs_clarification=False,
        actions=[
            ProposedAction(
                operation="create_report",
                payload=ActionPayload(
                    name="Mercado de novembro",
                    rows=["category"],
                    columns=["month"],
                    metrics=["expense_minor"],
                    chart="column",
                    order_by="expense_minor",
                    limit=1000,
                    filters=QueryFilters(
                        category_id=category,
                        start_date="2026-11-01",
                        end_date="2026-12-01",
                        basis="accrual",
                    ),
                ),
            )
        ],
    )
    token = asyncio.run(agent.apply_interpretation(interpretation, 123, 123)).confirmation_token
    assert token
    agent.confirm(token, 123, 123)
    report = agent.service.snapshot()["reports"][0]
    reply = asyncio.run(agent.answer_query(QueryRequest(kind="report", report_id=report["id"])))
    assert "1111" in reply.text
    assert "2222" not in reply.text and "9000" not in reply.text
    assert len(agent.service.snapshot()["transactions"]) == 3
