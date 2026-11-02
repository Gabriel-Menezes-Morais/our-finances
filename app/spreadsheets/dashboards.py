"""Shared chart/filter specifications without implying external publication."""

from __future__ import annotations

from typing import Any

from app.analytics.charts import chart_data


def build_dashboard(
    snapshot: dict[str, Any], filters: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "workspace_id": snapshot["workspace_id"],
        "revision": snapshot.get("revision", 0),
        "filters": filters or {},
        "charts": [
            chart_data(snapshot, filters, kind)
            for kind in ("monthly", "annual", "categories", "pareto", "budgets", "heatmap")
        ],
        "filter_dimensions": [
            "start_date",
            "end_date",
            "area_ids",
            "category_ids",
            "project_ids",
            "responsible_ids",
            "account_ids",
            "types",
            "statuses",
        ],
        "native_object_status": "pending_live_connection",
        "destination_differences": {
            "excel": "Native charts, pivot objects and slicers require authorized tenant proof",
            "sheets": "Native chart specifications and slicers require authorized workbook proof",
        },
    }
