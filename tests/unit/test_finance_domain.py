"""Financial facts, rollback and identity are tested against a real offline DB."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db import Database
from app.domain import DomainError, FinanceService
from app.models import AppliedCommand, AuditEvent, OutboxJob


@pytest.fixture
def service() -> FinanceService:
    database = Database("sqlite:///:memory:")
    database.initialize()
    return FinanceService(database, 123)


def apply(service: FinanceService, operation: str, **payload: Any) -> dict[str, Any]:
    revision = service.snapshot()["revision"]
    return service.execute(operation, payload, idempotency_key=f"test:{revision}")


def expense(service: FinanceService, amount: int = 1001, **fields: Any) -> dict[str, Any]:
    return apply(
        service,
        "create_transaction",
        type="expense",
        amount_minor=amount,
        occurrence_date="2026-01-31",
        **fields,
    )


def test_split_transaction_has_one_fact_and_exact_allocations(service: FinanceService) -> None:
    first = apply(service, "create_category", name="Educação")["id"]
    second = apply(service, "create_category", name="Trabalho")["id"]
    expense(
        service,
        60000,
        allocations=[
            {"category_id": first, "amount_minor": 30000},
            {"category_id": second, "amount_minor": 30000},
        ],
    )
    snap = service.snapshot()
    assert len(snap["transactions"]) == 1
    assert len(snap["allocations"]) == 2
    assert sum(a["amount_minor"] for a in snap["allocations"]) == 60000


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, "100", None])
def test_invalid_money_rolls_back(service: FinanceService, amount: Any) -> None:
    with pytest.raises(DomainError):
        expense(service, amount)
    assert service.snapshot()["revision"] == 0
    assert service.snapshot()["transactions"] == []
    with service.database.session() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxJob)) == 0


def test_bad_split_is_atomic(service: FinanceService) -> None:
    with pytest.raises(DomainError, match="soma"):
        expense(service, 100, allocations=[{"amount_minor": 99}])
    assert not service.snapshot()["transactions"]


def test_idempotency_replay_and_legitimate_equal_purchases(service: FinanceService) -> None:
    payload = {"type": "expense", "amount_minor": 100, "occurrence_date": "2026-01-01"}
    first = service.execute("create_transaction", payload, idempotency_key="source1")
    assert service.execute("create_transaction", payload, idempotency_key="source1") == first
    service.execute("create_transaction", payload, idempotency_key="source2")
    assert len(service.snapshot()["transactions"]) == 2
    with pytest.raises(DomainError) as caught:
        service.execute(
            "create_transaction", {**payload, "amount_minor": 101}, idempotency_key="source1"
        )
    assert caught.value.code == "idempotency_conflict"


def test_batch_rolls_back_all_actions(service: FinanceService) -> None:
    with pytest.raises(DomainError):
        service.execute_batch(
            [
                {"operation": "create_area", "payload": {"name": "Saúde"}},
                {"operation": "create_transaction", "payload": {"amount_minor": -1}},
            ],
            idempotency_key="batch",
        )
    assert service.snapshot()["areas"] == []
    assert service.snapshot()["revision"] == 0


def test_batch_references_resolve_only_prior_entity_ids_atomically(service: FinanceService) -> None:
    actions = [
        {"operation": "create_area", "payload": {"name": "Saúde"}},
        {"operation": "create_category", "payload": {"name": "Academia", "area_id": "$0"}},
        {
            "operation": "create_transaction",
            "payload": {
                "type": "expense",
                "amount_minor": 200,
                "occurrence_date": "2026-01-01",
                "allocations": [{"amount_minor": 200, "category_id": "$1"}],
            },
        },
    ]
    first = service.execute_batch(actions, idempotency_key="batch-ref")
    assert service.execute_batch(actions, idempotency_key="batch-ref") == first
    snap = service.snapshot()
    assert snap["categories"][0]["area_id"] == snap["areas"][0]["id"]
    assert snap["allocations"][0]["category_id"] == snap["categories"][0]["id"]
    assert snap["revision"] == 1
    for payload in ({"name": "$0"}, {"name": "Inválido", "area_id": "$1"}):
        with pytest.raises(DomainError) as caught:
            service.execute_batch(
                [{"operation": "create_category", "payload": payload}],
                idempotency_key=f"invalid-ref:{payload}",
            )
        assert caught.value.code == "invalid_batch_reference"
    assert snap["revision"] == 1


def test_optimistic_revision_and_atomic_audit_outbox(service: FinanceService) -> None:
    apply(service, "create_area", name="Saúde")
    with pytest.raises(DomainError) as caught:
        service.execute(
            "create_area", {"name": "Casa"}, idempotency_key="stale", expected_revision=0
        )
    assert caught.value.code == "revision_conflict"
    with service.database.session() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxJob)) == 1
        assert session.scalar(select(func.count()).select_from(AppliedCommand)) == 1


def test_concurrent_same_source_applies_once(service: FinanceService) -> None:
    def run(_: int) -> str:
        return service.execute("create_area", {"name": "Casa"}, idempotency_key="same")["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(run, range(8)))
    assert len(set(ids)) == 1
    assert service.snapshot()["revision"] == 1


def test_workspace_references_and_explicit_workspace_are_authorized(
    service: FinanceService,
) -> None:
    area_id = apply(service, "create_area", name="Casa")["id"]
    other = FinanceService(service.database, 456)
    with pytest.raises(DomainError):
        apply(other, "create_category", name="Moradia", area_id=area_id)
    with pytest.raises(DomainError):
        FinanceService(service.database, 456, service.snapshot()["workspace_id"]).snapshot()


def test_category_cycle_type_collision_and_merge(service: FinanceService) -> None:
    parent = apply(service, "create_category", name="Saúde")["id"]
    child = apply(service, "create_category", name="Consultas", parent_id=parent)["id"]
    with pytest.raises(DomainError) as caught:
        apply(service, "update_category", id=parent, parent_id=child)
    assert caught.value.code == "category_cycle"
    with pytest.raises(DomainError):
        apply(service, "create_category", name="SALÁRIO", type="income", parent_id=parent)
    target = apply(service, "create_category", name="Bem-estar")["id"]
    expense(service, allocations=[{"category_id": parent, "amount_minor": 1001}])
    apply(service, "merge_category", id=parent, target_id=target)
    snap = service.snapshot()
    assert snap["allocations"][0]["category_id"] == target
    assert next(c for c in snap["categories"] if c["id"] == child)["parent_id"] == target
    assert next(c for c in snap["categories"] if c["id"] == parent)["active"] is False


def test_refund_is_linked_and_cannot_exceed_original(service: FinanceService) -> None:
    category = apply(service, "create_category", name="Casa")["id"]
    original = expense(service, 101, allocations=[{"amount_minor": 101, "category_id": category}])[
        "id"
    ]
    apply(service, "refund_transaction", id=original, amount_minor=51, occurrence_date="2026-02-01")
    with pytest.raises(DomainError):
        apply(
            service,
            "refund_transaction",
            id=original,
            amount_minor=51,
            occurrence_date="2026-02-01",
        )
    with pytest.raises(DomainError):
        apply(service, "cancel_transaction", id=original)
    snap = service.snapshot()
    assert snap["transactions"][1]["type"] == "refund"
    assert snap["transactions"][1]["refund_of"] == original
    assert sum(a["amount_minor"] for a in snap["allocations"]) == 152


def test_transfer_and_card_settlement_do_not_create_consumption(service: FinanceService) -> None:
    bank = apply(service, "create_account", name="Banco", type="bank")["id"]
    card = apply(service, "create_account", name="Cartão", type="card", closing_day=20, due_day=5)[
        "id"
    ]
    apply(
        service,
        "settle_card",
        account_id=bank,
        to_account_id=card,
        amount_minor=5000,
        occurrence_date="2026-02-05",
    )
    snap = service.snapshot()
    assert snap["transactions"][0]["type"] == "transfer"
    assert snap["transactions"][0]["purpose"] == "card_settlement"
    assert snap["allocations"] == []
    with pytest.raises(DomainError):
        apply(
            service,
            "create_transaction",
            type="transfer",
            account_id=bank,
            to_account_id=bank,
            amount_minor=1,
            occurrence_date="2026-01-01",
        )


def test_installment_residue_card_calendar_and_february(service: FinanceService) -> None:
    card = apply(service, "create_account", name="Cartão", type="card", closing_day=20, due_day=5)[
        "id"
    ]
    expense(service, 1001, account_id=card, installment_count=3)
    installments = service.snapshot()["installments"]
    assert [i["amount_minor"] for i in installments] == [334, 334, 333]
    assert [i["due_date"] for i in installments] == ["2026-03-05", "2026-04-05", "2026-05-05"]
    # Calendar-day anchors survive short months.
    expense(service, 10, installment_count=3, first_due_date="2026-01-31")
    assert [i["due_date"] for i in service.snapshot()["installments"][-3:]] == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
    ]


def test_recurrence_generation_idempotent_and_month_anchor(service: FinanceService) -> None:
    apply(
        service,
        "create_recurrence",
        name="Internet",
        frequency="month",
        next_date="2026-01-31",
        exceptions=["2026-02-28"],
        template={"type": "expense", "amount_minor": 9990},
    )
    apply(service, "generate_recurrences", through_date="2026-03-31")
    apply(service, "generate_recurrences", through_date="2026-03-31")
    assert [t["occurrence_date"] for t in service.snapshot()["transactions"]] == [
        "2026-01-31",
        "2026-03-31",
    ]


def test_null_and_zero_budgets_goals_no_fake_income_and_missing_assets(
    service: FinanceService,
) -> None:
    for name, amount in [("Sem limite", None), ("Zero", 0)]:
        apply(
            service,
            "create_budget",
            name=name,
            amount_minor=amount,
            period="month",
            start_date="2026-01-01",
            carryover=True,
        )
    goal = apply(service, "create_goal", name="Reserva", target_minor=10000)["id"]
    apply(
        service,
        "create_contribution",
        goal_id=goal,
        amount_minor=1000,
        occurrence_date="2026-01-01",
    )
    apply(
        service, "create_asset", name="Imóvel sem avaliação", value_minor=None, as_of="2026-01-01"
    )
    snap = service.snapshot()
    assert [b["amount_minor"] for b in snap["budgets"]] == [None, 0]
    assert not snap["transactions"]
    assert snap["assets"][0]["value_minor"] is None


def test_undo_restores_facts_with_new_revision_and_preserves_audit(service: FinanceService) -> None:
    expense(service, 100)
    apply(service, "undo")
    assert not service.snapshot()["transactions"]
    assert service.snapshot()["revision"] == 2
    with pytest.raises(DomainError):
        apply(service, "undo")
    with service.database.session() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 2


def test_update_preserves_id_revises_and_does_not_overwrite_split(service: FinanceService) -> None:
    original = expense(service, 100)["id"]
    apply(service, "update_transaction", id=original, amount_minor=200, description="Corrigido")
    tx = service.snapshot()["transactions"][0]
    assert (tx["id"], tx["amount_minor"], tx["revision"]) == (original, 200, 2)


def test_fx_requires_explicit_provenance_and_uses_decimal(service: FinanceService) -> None:
    with pytest.raises(DomainError):
        expense(service, fx_rate=5.1)
    expense(service, currency="USD", fx_rate="5.1000", fx_date="2026-01-31", fx_source="informado")
    tx = service.snapshot()["transactions"][0]
    assert tx["fx_rate"] == "5.1000"
    assert tx["base_amount_minor"] == 5105
    assert tx["fx_rounding"] == "half_even"


def test_currency_minor_units_and_missing_fx_are_explicit(service: FinanceService) -> None:
    expense(
        service, 1, currency="JPY", fx_rate="0.035", fx_date="2026-01-31", fx_source="informado"
    )
    expense(
        service, 1000, currency="KWD", fx_rate="16", fx_date="2026-01-31", fx_source="informado"
    )
    expense(service, 200, currency="USD")
    txs = service.snapshot()["transactions"]
    assert txs[0]["base_amount_minor"] == 4
    assert txs[1]["base_amount_minor"] == 1600
    assert "base_amount_minor" not in txs[2]


def test_category_alias_collision_and_parent_type_edit(service: FinanceService) -> None:
    parent = apply(service, "create_category", name="Casa", aliases=["Moradia"])["id"]
    with pytest.raises(DomainError):
        apply(service, "create_category", name="casa")
    with pytest.raises(DomainError):
        apply(service, "create_category", name="moradia")
    apply(service, "create_category", name="Aluguel", parent_id=parent)
    with pytest.raises(DomainError):
        apply(service, "update_category", id=parent, type="income")


def test_pause_applies_to_cancellation_and_cannot_abuse_archive(service: FinanceService) -> None:
    original = expense(service)["id"]
    apply(service, "set_operations", flags={"mutations": True})
    with pytest.raises(DomainError) as caught:
        apply(service, "cancel_transaction", id=original)
    assert caught.value.code == "paused"
    apply(service, "set_operations", flags={"mutations": False})
    area = apply(service, "create_area", name="Casa")["id"]
    with pytest.raises(DomainError):
        apply(service, "archive_area", id=area, name="")


def test_single_allocation_amount_only_correction(service: FinanceService) -> None:
    category = apply(service, "create_category", name="Almoço")["id"]
    original = expense(
        service, 1234, allocations=[{"amount_minor": 1234, "category_id": category}]
    )["id"]
    apply(service, "update_transaction", id=original, amount_minor=2500)
    snap = service.snapshot()
    assert snap["transactions"][0]["amount_minor"] == 2500
    assert snap["allocations"][0]["amount_minor"] == 2500


def test_merge_updates_nested_future_references_and_scenario_collisions(
    service: FinanceService,
) -> None:
    source = apply(service, "create_category", name="Antiga")["id"]
    target = apply(service, "create_category", name="Atual")["id"]
    apply(
        service,
        "create_recurrence",
        name="Cobrança",
        frequency="month",
        next_date="2026-01-31",
        template={
            "type": "expense",
            "amount_minor": 100,
            "allocations": [{"category_id": source, "amount_minor": 100}],
        },
    )
    apply(
        service,
        "create_report",
        name="Visão",
        rows=["category"],
        filters={"category_ids": [source]},
    )
    apply(
        service,
        "create_scenario",
        name="Hipótese",
        assumptions={"category_reductions": {source: "0.2"}},
    )
    apply(service, "merge_category", id=source, target_id=target)
    apply(service, "generate_recurrences", through_date="2026-01-31")
    snap = service.snapshot()
    assert snap["allocations"][0]["category_id"] == target
    assert snap["reports"][0]["filters"]["category_ids"] == [target]
    assert snap["scenarios"][0]["assumptions"]["category_reductions"] == {target: "0.2"}


def test_recurrence_rewind_cannot_duplicate_occurrence(service: FinanceService) -> None:
    recurrence = apply(
        service,
        "create_recurrence",
        name="Cobrança",
        frequency="month",
        next_date="2026-01-01",
        template={"type": "expense", "amount_minor": 100},
    )["id"]
    apply(service, "generate_recurrences", through_date="2026-02-01")
    apply(service, "update_recurrence", id=recurrence, next_date="2026-01-01")
    apply(service, "generate_recurrences", through_date="2026-02-01")
    assert len(service.snapshot()["transactions"]) == 2


def test_card_payment_partial_and_cancellation_restore_commitment_and_ids(
    service: FinanceService,
) -> None:
    bank = apply(service, "create_account", name="Banco", type="bank")["id"]
    card = apply(service, "create_account", name="Cartão", type="card", closing_day=20, due_day=5)[
        "id"
    ]
    purchase = expense(service, 100, account_id=card)["id"]
    original_installment = service.snapshot()["installments"][0]["id"]
    payment = apply(
        service,
        "settle_card",
        account_id=bank,
        to_account_id=card,
        amount_minor=50,
        occurrence_date="2026-03-05",
    )["id"]
    installment = service.snapshot()["installments"][0]
    assert installment["paid_minor"] == 50 and installment["settled"] is False
    apply(service, "update_transaction", id=purchase, description="Compra corrigida")
    assert service.snapshot()["installments"][0]["id"] == original_installment
    with pytest.raises(DomainError):
        apply(service, "update_transaction", id=purchase, amount_minor=200)
    with pytest.raises(DomainError):
        apply(service, "cancel_transaction", id=purchase)
    apply(service, "cancel_transaction", id=payment)
    assert service.snapshot()["installments"][0]["paid_minor"] == 0
    apply(service, "cancel_transaction", id=purchase)
    assert service.snapshot()["installments"][0]["active"] is False


def test_workspace_configuration_and_config_duplication(service: FinanceService) -> None:
    apply(service, "configure_workspace", name="Fictício", timezone="UTC", currency="USD")
    assert service.snapshot()["currency"] == "USD"
    report = apply(
        service, "create_report", name="Mensal", rows=["category"], metrics=["expense_minor"]
    )["id"]
    duplicate = apply(service, "duplicate_report", id=report, name="Cópia")["id"]
    assert duplicate != report
    expense(service)
    with pytest.raises(DomainError):
        apply(service, "configure_workspace", currency="BRL")


def test_card_refund_credits_commitments_without_inventing_cash(service: FinanceService) -> None:
    card = apply(service, "create_account", name="Cartão", type="card", closing_day=20, due_day=5)[
        "id"
    ]
    purchase = expense(service, 101, account_id=card, installment_count=2)["id"]
    refund = apply(
        service, "refund_transaction", id=purchase, amount_minor=75, occurrence_date="2026-02-01"
    )["id"]
    snap = service.snapshot()
    assert sum(i.get("refunded_minor", 0) for i in snap["installments"]) == 75
    assert sum(i["amount_minor"] - i.get("refunded_minor", 0) for i in snap["installments"]) == 26
    assert len(snap["transactions"]) == 2
    apply(service, "cancel_transaction", id=refund)
    assert sum(i.get("refunded_minor", 0) for i in service.snapshot()["installments"]) == 0


def test_card_calendar_anchor_and_date_correction(service: FinanceService) -> None:
    card = apply(service, "create_account", name="Cartão", type="card", closing_day=20, due_day=31)[
        "id"
    ]
    purchase = expense(service, 100, account_id=card, installment_count=3)["id"]
    assert [i["due_date"] for i in service.snapshot()["installments"]] == [
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
    ]
    apply(service, "update_transaction", id=purchase, description="Corrigido")
    assert [i["due_date"] for i in service.snapshot()["installments"]] == [
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
    ]
    apply(service, "update_transaction", id=purchase, occurrence_date="2026-01-10")
    assert service.snapshot()["installments"][0]["due_date"] == "2026-01-31"


def test_saved_scenario_extended_assumptions_are_validated(service: FinanceService) -> None:
    apply(
        service,
        "create_scenario",
        name="Renda informada",
        assumptions={
            "income_minor": 500000,
            "extra_expenses_minor": 10000,
            "income_change_rate": "0",
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
            "include_recurrences": True,
            "extraordinary_expenses": [
                {"date": "2026-02-01", "amount_minor": 1000, "currency": "BRL"}
            ],
        },
    )
    with pytest.raises(DomainError):
        apply(
            service, "create_scenario", name="Inválido", assumptions={"income_change_rate": "NaN"}
        )
    other = FinanceService(service.database, 456)
    category = apply(other, "create_category", name="Privada")["id"]
    with pytest.raises(DomainError):
        apply(service, "create_report", name="Sem acesso", filters={"category_ids": [category]})
