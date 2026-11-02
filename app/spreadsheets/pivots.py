"""Native-object publication specification; live execution intentionally deferred."""

from __future__ import annotations

from typing import Any

from app.analytics.reports import ReportDefinition, pivot

ADDITIVE = {"expense_minor", "income_minor", "net_minor", "allocation_count"}


def build_pivot_spec(
    snapshot: dict[str, Any],
    definition: dict[str, Any] | ReportDefinition,
    destination: str = "excel",
) -> dict[str, Any]:
    if destination not in {"excel", "sheets"}:
        raise ValueError("Destination must be excel or sheets")
    result = pivot(snapshot, definition)
    report = result["definition"]
    native = [m for m in report["metrics"] if m in ADDITIVE]
    auxiliary = [m for m in report["metrics"] if m not in ADDITIVE]
    return {
        "schema_version": 1,
        "destination": destination,
        "workspace_id": snapshot["workspace_id"],
        "revision": snapshot.get("revision", 0),
        "definition": report,
        "source": "filtered_allocation_facts",
        "currency_partition_required": True,
        "row_dimensions": list(dict.fromkeys(["currency", *report["rows"]])),
        "column_dimensions": report["columns"],
        "native_measures": [
            {
                "field": "allocation_id" if m == "allocation_count" else m,
                **({"output_metric": "allocation_count"} if m == "allocation_count" else {}),
                "aggregation": "count" if m == "allocation_count" else "sum",
                "grain": "allocation",
            }
            for m in native
        ],
        "auxiliary_measures": [
            {"metric": m, "source": "analytics_engine", "non_additive": True} for m in auxiliary
        ],
        "expected_totals_by_currency": result["totals_by_currency"],
        "preserve_manual_objects": True,
        "execution_status": "pending_live_connection",
        "native_objects_created": False,
        "required_proof": [
            "Create native pivot object in authorized workbook",
            "Read current revision, grouped values and currency totals",
            "Change axes and filters, recreate generated object preserving manual objects",
            "Replay same revision and verify idempotence",
            "Download workbook and verify native object preservation",
        ],
    }
