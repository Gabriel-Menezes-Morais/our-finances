from copy import deepcopy

import pytest

from app.analytics import compute, pivot
from app.analytics.reports import ReportDefinition


@pytest.fixture
def snapshot():
    def tx(identifier, kind, amount, day="2026-10-05", **extra):
        return {
            "id": identifier,
            "type": kind,
            "amount_minor": amount,
            "currency": "BRL",
            "occurrence_date": day,
            "competence_date": day,
            "settlement_date": day,
            "status": "settled",
            "account_id": "bank",
            "revision": 1,
            **extra,
        }

    return {
        "workspace_id": "w",
        "revision": 7,
        "currency": "BRL",
        "timezone": "America/Sao_Paulo",
        "as_of": "2026-11-15",
        "categories": [
            {"id": "parent", "name": "Vida"},
            {"id": "a", "name": "Educação", "parent_id": "parent", "area_id": "learn"},
            {"id": "b", "name": "Trabalho", "parent_id": "parent"},
        ],
        "transactions": [
            tx("split", "expense", 60000),
            tx("salary", "income", 200000),
            tx("refund", "refund", 10000, refund_of="split"),
            tx("transfer", "transfer", 50000, to_account_id="card", purpose="card_settlement"),
            tx("usd", "expense", 1234, currency="USD"),
        ],
        "allocations": [
            {"id": "x", "transaction_id": "split", "category_id": "a", "amount_minor": 30000},
            {"id": "y", "transaction_id": "split", "category_id": "b", "amount_minor": 30000},
            {"id": "z", "transaction_id": "refund", "category_id": "a", "amount_minor": 10000},
        ],
        "accounts": [
            {
                "id": "bank",
                "name": "Banco",
                "currency": "BRL",
                "opening_balance_minor": 100000,
                "opening_date": "2026-01-01",
            },
            {"id": "card", "name": "Cartão", "currency": "BRL", "opening_balance_minor": None},
        ],
    }


def test_split_refund_currency_and_transfer(snapshot):
    result = compute(snapshot)
    brl, usd = result["totals_by_currency"]
    assert brl["currency"] == "BRL"
    assert brl["expense_minor"] == 50000
    assert brl["income_minor"] == 200000
    assert brl["expense_transaction_count"] == 1
    assert brl["transaction_count"] == 3
    assert brl["ticket_minor"] == "60000"
    assert usd["expense_minor"] == 1234
    assert result["balances"][1]["balance_minor"] is None
    assert result["balances"][0]["balance_minor"] == 200000


def test_mandatory_single_purchase_split(snapshot):
    snapshot["transactions"] = snapshot["transactions"][:1]
    snapshot["allocations"] = snapshot["allocations"][:2]
    total = compute(snapshot)["totals_by_currency"][0]
    assert total["expense_minor"] == 60000
    assert total["transaction_count"] == 1
    assert total["allocation_count"] == 2
    assert total["ticket_minor"] == "60000"
    groups = pivot(
        snapshot,
        {
            "rows": ["category"],
            "columns": ["month"],
            "metrics": ["expense_minor", "transaction_count", "ticket_minor"],
        },
    )
    assert [r["expense_minor"] for r in groups["cells"]] == [30000, 30000]
    assert groups["totals_by_currency"][0]["transaction_count"] == 1


def test_parent_filter_no_double_count(snapshot):
    parent = compute(snapshot, {"category_ids": ["parent", "a"]})
    assert parent["totals_by_currency"][0]["expense_minor"] == 50000
    child = compute(snapshot, {"category_ids": ["a"]})
    assert child["totals_by_currency"][0]["expense_minor"] == 20000
    assert child["totals_by_currency"][0]["ticket_minor"] == "30000"


def test_filter_intersections_and_cash_date(snapshot):
    snapshot["transactions"][0]["settlement_date"] = None
    assert (
        compute(snapshot, {"basis": "cash", "types": ["expense"]})["totals_by_currency"][0][
            "currency"
        ]
        == "USD"
    )
    assert (
        compute(snapshot, {"area_ids": ["learn"], "category_ids": ["b"]})["totals_by_currency"]
        == []
    )


def test_zero_denominators_and_missing_history(snapshot):
    result = compute(snapshot, {"types": ["expense"], "currencies": ["BRL"]})
    assert result["totals_by_currency"][0]["saving_rate"] is None
    assert result["monthly"][0]["rolling_3_month_mean_minor"] is None
    assert result["monthly"][0]["month_change_rate"] is None
    empty = compute(snapshot, {"category_ids": []})
    assert empty["coverage"]["empty"] is True


def test_missing_months_and_incomplete_period(snapshot):
    result = compute(
        snapshot, {"start_date": "2026-09-15", "end_date": "2026-11-15", "currencies": ["BRL"]}
    )
    assert [r["expense_minor"] for r in result["monthly"]] == [0, 50000, 0]
    assert result["monthly"][-1]["rolling_3_month_mean_minor"].startswith("16666.")
    assert result["monthly"][0]["incomplete_period"] is True
    assert result["monthly"][1]["incomplete_period"] is False


def test_budgets_zero_none_hierarchy_and_carryover(snapshot):
    snapshot["budgets"] = [
        {
            "id": "budget",
            "name": "Vida",
            "currency": "BRL",
            "period": "month",
            "start_date": "2026-10-01",
            "amount_minor": 60000,
            "category_id": "parent",
            "thresholds": ["0.8", "1"],
            "carryover": True,
        },
        {"id": "unlimited", "start_date": "2026-10-01", "amount_minor": None},
        {"id": "zero", "start_date": "2026-10-01", "amount_minor": 0},
    ]
    budgets = compute(snapshot)["budgets"]
    october, november = [r for r in budgets if r["id"] == "budget"]
    assert october["actual_minor"] == 50000
    assert october["remaining_minor"] == 10000
    assert october["thresholds_reached"] == ["0.8"]
    assert november["carryover_applied_minor"] == 10000
    assert november["limit_minor"] == 70000
    assert all(r["remaining_minor"] is None for r in budgets if r["id"] == "unlimited")
    assert all(r["consumed_rate"] is None and r["zero_limit"] for r in budgets if r["id"] == "zero")


def test_budget_filters_do_not_broaden_caller_population(snapshot):
    snapshot["budgets"] = [
        {"id": "budget", "start_date": "2026-10-01", "amount_minor": 100000, "category_id": "a"}
    ]
    assert all(
        r["actual_minor"] == 0 for r in compute(snapshot, {"category_ids": ["b"]})["budgets"]
    )


def test_anomaly_explained_without_fraud_claim(snapshot):
    template = snapshot["transactions"][0]
    snapshot["transactions"] = [
        {**template, "id": str(i), "amount_minor": amount}
        for i, amount in enumerate([1000, 1000, 1000, 1000, 10000])
    ]
    snapshot["allocations"] = []
    result = compute(snapshot)
    assert [a["transaction_id"] for a in result["anomalies"]] == ["4"]
    assert result["anomalies"][0]["median_absolute_deviation_minor"] == "0"


def test_goals_unknown_target_zero_target_and_contributions(snapshot):
    snapshot["goals"] = [
        {"id": "g", "target_minor": 100000, "deadline": "2026-12-15", "currency": "BRL"},
        {"id": "z", "target_minor": 0},
    ]
    snapshot["contributions"] = [
        {"goal_id": "g", "amount_minor": 25000, "occurrence_date": "2026-10-05"}
    ]
    goals = compute(snapshot)["goals"]
    assert goals[0]["progress_rate"] == "0.25"
    assert goals[0]["remaining_minor"] == 75000
    assert goals[1]["progress_rate"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"sql": "DROP TABLE"},
        {"basis": "sql"},
        {"start_date": "2026-11-10", "end_date": "2026-10-01"},
    ],
)
def test_reject_untrusted_filter_schema(snapshot, bad):
    with pytest.raises(ValueError):
        compute(snapshot, bad)


def test_cross_workspace_and_bad_allocation_rejected(snapshot):
    snapshot["transactions"][0]["workspace_id"] = "other"
    with pytest.raises(ValueError, match="workspace"):
        compute(snapshot)
    snapshot["transactions"][0].pop("workspace_id")
    snapshot["allocations"][0]["amount_minor"] += 1
    with pytest.raises(ValueError, match="reconcile"):
        compute(snapshot)


def test_report_closed_dimensions_bounded_and_original_unchanged(snapshot):
    before = deepcopy(snapshot)
    with pytest.raises(ValueError):
        ReportDefinition(rows=["=WEBSERVICE()"])
    with pytest.raises(ValueError):
        pivot(snapshot, {"max_cells": 1})
    pivot(snapshot, {"rows": ["category"], "metrics": ["transaction_count"]})
    assert snapshot == before


def test_period_is_half_open_and_end_of_month_cannot_leak(snapshot):
    template = snapshot["transactions"][0]
    snapshot["transactions"] = [
        {**template, "id": "oct", "amount_minor": 10000},
        {
            **template,
            "id": "nov",
            "occurrence_date": "2026-11-01",
            "competence_date": "2026-11-01",
            "settlement_date": "2026-11-01",
            "amount_minor": 90000,
        },
    ]
    snapshot["allocations"] = []
    result = compute(snapshot, {"start_date": "2026-10-01", "end_date": "2026-11-01"})
    assert result["totals_by_currency"][0]["expense_minor"] == 10000
    assert result["metadata"]["end_date"] == "2026-11-01"
    assert result["metadata"]["end_date_inclusive"] == "2026-10-31"
    assert len(result["monthly"]) == 1
    assert result["monthly"][0]["incomplete_period"] is False


def test_parent_classifications_and_transaction_override(snapshot):
    snapshot["categories"][0].update(variability="fixo", necessity="essencial")
    snapshot["transactions"][0]["necessity"] = "escolha própria"
    result = compute(snapshot, {"types": ["expense"], "category_ids": ["a"]})
    assert result["classifications"][0]["variability"] == "fixo"
    assert result["classifications"][0]["necessity"] == "escolha própria"


def test_filtered_budget_keeps_true_carryover(snapshot):
    snapshot["budgets"] = [
        {"id": "budget", "start_date": "2026-10-01", "amount_minor": 60000, "carryover": True}
    ]
    result = compute(
        snapshot, {"category_ids": ["b"], "start_date": "2026-11-01", "end_date": "2026-12-01"}
    )
    assert result["budgets"][0]["carryover_applied_minor"] == 10000
    assert result["budgets"][0]["limit_minor"] == 70000


def test_tiny_minor_units_mean_and_dispersion_exact(snapshot):
    template = snapshot["transactions"][0]
    snapshot["transactions"] = [
        {**template, "id": "one", "amount_minor": 1},
        {**template, "id": "two", "amount_minor": 2},
    ]
    snapshot["allocations"] = []
    total = compute(snapshot)["totals_by_currency"][0]
    assert total["ticket_minor"] == "1.5"
    assert total["population_stddev_minor"] == "0.5"


def test_card_cash_waits_for_payment_and_preserves_purchase_category():
    snapshot = {
        "workspace_id": "w",
        "revision": 1,
        "accounts": [{"id": "card", "type": "card"}, {"id": "bank", "type": "bank"}],
        "transactions": [
            {
                "id": "purchase",
                "type": "expense",
                "amount_minor": 10001,
                "currency": "BRL",
                "account_id": "card",
                "occurrence_date": "2026-01-31",
                "competence_date": "2026-01-31",
                "settlement_date": "2026-01-31",
                "status": "settled",
            },
            {
                "id": "payment",
                "type": "transfer",
                "amount_minor": 5001,
                "currency": "BRL",
                "account_id": "bank",
                "to_account_id": "card",
                "occurrence_date": "2026-03-05",
                "settlement_date": "2026-03-05",
                "status": "settled",
            },
        ],
        "allocations": [
            {"id": "a", "transaction_id": "purchase", "category_id": "a", "amount_minor": 5000},
            {"id": "b", "transaction_id": "purchase", "category_id": "b", "amount_minor": 5001},
        ],
        "installments": [
            {
                "id": "i",
                "transaction_id": "purchase",
                "amount_minor": 10001,
                "paid_minor": 5001,
                "payments": [{"transaction_id": "payment", "amount_minor": 5001}],
            }
        ],
    }
    january = compute(
        snapshot, {"basis": "cash", "start_date": "2026-01-01", "end_date": "2026-02-01"}
    )
    assert january["totals_by_currency"] == []
    march = compute(
        snapshot, {"basis": "cash", "start_date": "2026-03-01", "end_date": "2026-04-01"}
    )
    assert march["totals_by_currency"][0]["expense_minor"] == 5001
    assert march["totals_by_currency"][0]["expense_transaction_count"] == 1
    assert sum(r["expense_minor"] for r in march["categories"]) == 5001
    assert compute(snapshot)["totals_by_currency"][0]["expense_minor"] == 10001
    snapshot["installments"][0]["payments"][0]["amount_minor"] = 1
    tiny = compute(snapshot, {"basis": "cash", "types": ["expense"]})
    assert tiny["totals_by_currency"][0]["expense_minor"] == 1
    assert len(tiny["categories"]) == 1
    assert tiny["categories"][0]["category_id"] == "b"


def test_filtered_budget_remaining_uses_full_population_and_inactive_contributions(snapshot):
    snapshot["budgets"] = [
        {
            "id": "g",
            "amount_minor": 100000,
            "start_date": "2026-10-01",
            "category_id": "parent",
            "thresholds": ["0.5"],
        }
    ]
    budget = compute(
        snapshot, {"category_ids": ["b"], "start_date": "2026-10-01", "end_date": "2026-11-01"}
    )["budgets"][0]
    assert budget["actual_minor"] == 30000
    assert budget["budget_actual_minor"] == 50000
    assert budget["remaining_minor"] == 50000
    assert budget["thresholds_reached"] == ["0.5"]
    snapshot["goals"] = [{"id": "goal", "target_minor": 50000}]
    snapshot["contributions"] = [
        {"goal_id": "goal", "amount_minor": 40000, "occurrence_date": "2026-10-01", "active": False}
    ]
    assert compute(snapshot)["goals"][0]["contributed_minor"] == 0
