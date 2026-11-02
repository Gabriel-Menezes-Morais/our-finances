from copy import deepcopy

import pytest

from app.analytics.scenarios import scenario


def source():
    return {
        "workspace_id": "w",
        "revision": 1,
        "currency": "BRL",
        "as_of": "2026-11-01",
        "categories": [
            {"id": "food", "name": "Alimentação"},
            {"id": "delivery", "parent_id": "food", "name": "Delivery"},
        ],
        "recurrences": [
            {
                "id": "delivery",
                "next_date": "2026-11-05",
                "end_date": "2026-11-05",
                "template": {"type": "expense", "amount_minor": 10001, "category_id": "delivery"},
            },
            {
                "id": "salary",
                "next_date": "2026-11-05",
                "end_date": "2026-11-05",
                "template": {"type": "income", "amount_minor": 100000},
            },
        ],
    }


def test_scenario_reconciles_rounding_extra_expense_and_never_changes_actual():
    snapshot = source()
    before = deepcopy(snapshot)
    result = scenario(
        snapshot,
        {
            "category_reductions": {"food": "0.2", "delivery": "0.1"},
            "income_change_rate": "0.1",
            "extraordinary_expenses": [
                {"date": "2026-11-10", "amount_minor": 5000, "currency": "BRL"}
            ],
        },
    )
    assert result["baseline"]["totals_by_currency"][0]["expense_minor"] == 10001
    projection = result["projected"]["totals_by_currency"][0]
    assert projection["expense_minor"] == 13001
    assert projection["income_minor"] == 110000
    assert projection["net_minor"] == 96999
    assert snapshot == before


@pytest.mark.parametrize(
    "assumptions",
    [
        {"income_change_rate": "-1.1"},
        {"category_reductions": {"food": "1.01"}},
        {"category_reductions": {"food": "NaN"}},
        {"extraordinary_expenses": [{"date": "2020-01-01", "amount_minor": 5, "currency": "BRL"}]},
        {"formula": "=NOW()"},
    ],
)
def test_scenario_invalid_assumptions(assumptions):
    with pytest.raises(ValueError):
        scenario(source(), assumptions)


def test_split_scenario_reduces_only_requested_allocation():
    snapshot = source()
    snapshot["recurrences"] = []
    snapshot["transactions"] = [
        {
            "id": "split",
            "type": "expense",
            "amount_minor": 10000,
            "occurrence_date": "2026-11-05",
            "status": "pending",
        }
    ]
    snapshot["allocations"] = [
        {"transaction_id": "split", "category_id": "delivery", "amount_minor": 3000},
        {"transaction_id": "split", "category_id": "other", "amount_minor": 7000},
    ]
    result = scenario(snapshot, {"category_reductions": {"food": "0.2"}})
    assert result["projected"]["totals_by_currency"][0]["expense_minor"] == 9400
    assert result["baseline"]["totals_by_currency"][0]["expense_minor"] == 10000


def test_absolute_monthly_income_and_undated_expense_have_no_fake_cash_dates():
    result = scenario(
        source(),
        {
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
            "income_minor": 500000,
            "extra_expenses_minor": 20000,
        },
    )
    projected = result["projected"]["totals_by_currency"][0]
    assert projected["income_minor"] == 500000
    assert projected["expense_minor"] == 30001
    assert projected["closing_balance_minor"] is None
    assert result["monthly_adjustments"][0]["date"] is None
    assert result["undated_adjustments"][0]["date"] is None
    assert result["monthly_adjustments"][0]["income_delta_minor"] == 400000
    assert result["baseline"]["totals_by_currency"][0]["income_minor"] == 100000
