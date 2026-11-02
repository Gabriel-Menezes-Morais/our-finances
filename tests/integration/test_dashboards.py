from app.spreadsheets.dashboards import build_dashboard


def test_dashboard_filters_share_population_across_views():
    snapshot = {
        "workspace_id": "w",
        "revision": 3,
        "transactions": [
            {
                "id": "a",
                "type": "expense",
                "currency": "BRL",
                "amount_minor": 10000,
                "occurrence_date": "2026-10-01",
                "category_id": "a",
            },
            {
                "id": "b",
                "type": "expense",
                "currency": "BRL",
                "amount_minor": 20000,
                "occurrence_date": "2026-10-01",
                "category_id": "b",
            },
        ],
    }
    dashboard = build_dashboard(snapshot, {"category_ids": ["a"]})
    charts = {chart["kind"]: chart for chart in dashboard["charts"]}
    assert charts["monthly"]["series"][0]["values_minor"] == [10000]
    assert charts["categories"]["series"][0]["values_minor"] == [10000]
    assert dashboard["native_object_status"] == "pending_live_connection"
