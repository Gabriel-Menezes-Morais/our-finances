from copy import deepcopy

import pytest

from app.analytics.forecast import add_period, forecast


@pytest.fixture
def cash_snapshot():
    return {
        "workspace_id": "w",
        "revision": 2,
        "currency": "BRL",
        "as_of": "2026-01-31",
        "accounts": [{"id": "a", "currency": "BRL", "opening_balance_minor": None}],
        "transactions": [
            {
                "id": "parent",
                "type": "expense",
                "amount_minor": 10001,
                "currency": "BRL",
                "occurrence_date": "2026-01-31",
                "status": "pending",
                "account_id": "a",
            }
        ],
        "installments": [
            {
                "id": "i1",
                "transaction_id": "parent",
                "amount_minor": 5001,
                "due_date": "2026-02-15",
                "settled": False,
            },
            {
                "id": "i2",
                "transaction_id": "parent",
                "amount_minor": 5000,
                "due_date": "2026-03-15",
                "settled": False,
            },
        ],
        "recurrences": [
            {
                "id": "salary",
                "frequency": "month",
                "interval": 1,
                "next_date": "2026-01-31",
                "end_date": "2026-03-31",
                "exceptions": ["2026-02-28"],
                "template": {"type": "income", "amount_minor": 100000, "currency": "BRL"},
            }
        ],
    }


def test_cash_commitments_are_separate_unknown_opening_and_no_parent_duplicate(cash_snapshot):
    before = deepcopy(cash_snapshot)
    result = forecast(cash_snapshot)
    assert result["totals_by_currency"][0]["expense_minor"] == 10001
    assert result["totals_by_currency"][0]["income_minor"] == 200000
    assert result["totals_by_currency"][0]["closing_balance_minor"] is None
    assert all(not row["consumption_actual"] for row in result["items"])
    assert cash_snapshot == before


def test_month_end_recurrence_anchor_restored(cash_snapshot):
    result = forecast(cash_snapshot)
    recurring_dates = [row["date"] for row in result["items"] if row["source"] == "recurrence"]
    assert recurring_dates == ["2026-01-31", "2026-03-31"]
    from datetime import date

    assert add_period(date(2024, 2, 29), "year", 1) == date(2025, 2, 28)


def test_wealth_unknown_not_zero_and_debt_requires_rate_period(cash_snapshot):
    cash_snapshot["assets"] = [
        {"id": "home", "currency": "BRL", "value_minor": 100000},
        {"id": "unknown", "currency": "BRL", "value_minor": None},
    ]
    cash_snapshot["liabilities"] = [
        {"id": "loan", "currency": "BRL", "value_minor": 10000, "rate": "0.01"}
    ]
    result = forecast(cash_snapshot, {"debt_payment_minor": {"loan": 1000}})
    assert result["net_worth"][0]["net_worth_minor"] is None
    assert result["debts"][0]["schedule"] == []
    cash_snapshot["liabilities"][0]["rate_period"] = "month"
    result = forecast(cash_snapshot, {"debt_payment_minor": {"loan": 1000}, "debt_periods": 2})
    assert result["debts"][0]["schedule"][0] == {
        "period": 1,
        "interest_minor": 100,
        "payment_minor": 1000,
        "balance_minor": 9100,
    }
    assert result["debts"][0]["schedule"][1]["interest_minor"] == 91


def test_forecast_requires_explicit_anchor_and_rejects_unbounded_horizon():
    with pytest.raises(ValueError):
        forecast({"workspace_id": "w"})
    with pytest.raises(ValueError):
        forecast({"workspace_id": "w", "as_of": "2026-01-01"}, {"horizon_days": 999999})


def test_transfer_not_consumption(cash_snapshot):
    cash_snapshot["transactions"].append(
        {
            "id": "pay-card",
            "type": "transfer",
            "amount_minor": 90000,
            "occurrence_date": "2026-02-01",
            "status": "pending",
            "currency": "BRL",
        }
    )
    result = forecast(cash_snapshot)
    assert result["totals_by_currency"][0]["expense_minor"] == 10001


def test_partial_installment_payment_and_filtered_category_cash(cash_snapshot):
    cash_snapshot["installments"][0]["paid_minor"] = 1000
    assert forecast(cash_snapshot)["totals_by_currency"][0]["expense_minor"] == 9001
    cash_snapshot["allocations"] = [
        {"transaction_id": "parent", "category_id": "a", "amount_minor": 5000},
        {"transaction_id": "parent", "category_id": "b", "amount_minor": 5001},
    ]
    result = forecast(cash_snapshot, {"end_date": "2026-03-15", "filters": {"category_ids": ["a"]}})
    assert len(result["items"]) == 1
    assert result["items"][0]["date"] == "2026-02-15"
    assert result["items"][0]["amount_minor"] == 2000


def test_card_liability_not_subtracted_from_liquidity_twice(cash_snapshot):
    cash_snapshot["accounts"] = [
        {"id": "a", "type": "card", "currency": "BRL", "opening_balance_minor": 0},
        {"id": "bank", "type": "bank", "currency": "BRL", "opening_balance_minor": 100000},
    ]
    cash_snapshot["transactions"][0]["settlement_date"] = "2026-01-31"
    cash_snapshot["recurrences"] = []
    result = forecast(cash_snapshot, {"start_date": "2026-02-01"})
    assert result["totals_by_currency"][0]["opening_balance_minor"] == 100000
    assert result["totals_by_currency"][0]["closing_balance_minor"] == 89999
    assert all(r["account_id"] != "a" for r in result["balances"])


def test_materialized_recurrence_anchor_and_refund_not_income(cash_snapshot):
    cash_snapshot["recurrences"] = [
        {
            "id": "rent",
            "next_date": "2026-02-28",
            "anchor_day": 31,
            "template": {"type": "expense", "amount_minor": 10000},
        }
    ]
    cash_snapshot["transactions"].extend(
        [
            {
                "id": "existing",
                "type": "expense",
                "amount_minor": 10000,
                "currency": "BRL",
                "status": "settled",
                "occurrence_date": "2026-02-28",
                "recurrence_id": "rent",
                "recurrence_date": "2026-02-28",
            },
            {
                "id": "refund",
                "type": "refund",
                "amount_minor": 2000,
                "currency": "BRL",
                "status": "pending",
                "occurrence_date": "2026-03-10",
            },
        ]
    )
    result = forecast(cash_snapshot, {"end_date": "2026-04-01"})
    recurring = [r["date"] for r in result["items"] if r["source"] == "recurrence"]
    assert recurring == ["2026-03-31"]
    refund = next(r for r in result["items"] if r["type"] == "refund")
    assert refund["income_minor"] == 0
    assert refund["expense_minor"] == -2000
