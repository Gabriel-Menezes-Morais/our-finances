from app.analytics import pivot
from app.spreadsheets.pivots import build_pivot_spec
from app.spreadsheets.projection import build_projection


def test_pivot_axes_and_projection_are_deterministic_data_only():
    snapshot = {
        "workspace_id": "w",
        "revision": 2,
        "currency": "BRL",
        "transactions": [
            {"id": "tx", "type": "expense", "amount_minor": 60000, "occurrence_date": "2026-10-01"}
        ],
        "allocations": [
            {"id": "a", "transaction_id": "tx", "category_id": "a", "amount_minor": 30000},
            {"id": "b", "transaction_id": "tx", "category_id": "b", "amount_minor": 30000},
        ],
        "categories": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
    }
    definition = {
        "rows": ["category"],
        "columns": ["month"],
        "metrics": ["expense_minor", "transaction_count"],
    }
    result = pivot(snapshot, definition)
    assert len(result["cells"]) == 2
    assert result["totals_by_currency"][0]["transaction_count"] == 1
    modified = pivot(snapshot, {**definition, "rows": ["year"], "columns": []})
    assert len(modified["cells"]) == 1
    assert modified["cells"][0]["expense_minor"] == 60000
    spec = build_pivot_spec(snapshot, definition)
    assert spec["execution_status"] == "pending_live_connection"
    assert spec["native_measures"] == [
        {"field": "expense_minor", "aggregation": "sum", "grain": "allocation"}
    ]
    assert spec["auxiliary_measures"][0]["metric"] == "transaction_count"
    projection = build_projection(snapshot)
    assert projection["data_hash"] == build_projection(snapshot)["data_hash"]
    assert projection["publication_status"] == "local_projection_only"
