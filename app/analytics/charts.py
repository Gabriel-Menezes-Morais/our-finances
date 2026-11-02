"""Chart data specifications shared by reports and future destination adapters."""

from __future__ import annotations

from typing import Any, Literal

from app.analytics.metrics import compute

DashboardKind = Literal[
    "monthly", "annual", "categories", "pareto", "budgets", "heatmap", "distribution", "cashflow"
]


def chart_data(
    snapshot: dict[str, Any], filters: dict[str, Any] | None = None, kind: str = "monthly"
) -> dict[str, Any]:
    kind = {"category": "categories", "budget": "budgets"}.get(kind, kind)
    result = compute(snapshot, filters)
    metadata = result["metadata"]
    fields = {
        "monthly": ("monthly", "month", "expense_minor"),
        "annual": ("annual", "year", "expense_minor"),
        "categories": ("categories", "category", "expense_minor"),
        "pareto": ("categories", "category", "expense_minor"),
        "budgets": ("budgets", "name", "actual_minor"),
        "heatmap": ("daily", "date", "expense_minor"),
        "distribution": ("distributions", "range", "count"),
    }
    if kind == "cashflow":
        from app.analytics.forecast import forecast

        assumptions: dict[str, Any] = {
            k: v for k, v in (filters or {}).items() if k in {"start_date", "end_date"}
        }
        assumptions["filters"] = filters or {}
        projection = forecast(snapshot, assumptions)
        metadata = projection["metadata"]
        rows, label, value = projection["monthly"], "month", "net_minor"
    elif kind in fields:
        table, label, value = fields[kind]
        rows = result[table]
        if kind == "distribution":
            rows = [{**r, "range": f"{r['min_minor']}–{r['max_minor']} minor"} for r in rows]
    else:
        raise ValueError("Unsupported chart kind")
    series = []
    for currency in sorted({row["currency"] for row in rows}):
        selected = [row for row in rows if row["currency"] == currency]
        series.append(
            {
                "currency": currency,
                "labels": [str(row.get(label) or "Sem identificação") for row in selected],
                "values": [row.get(value) for row in selected],
                **(
                    {"values_minor": [row.get(value) for row in selected]}
                    if kind != "distribution"
                    else {}
                ),
                "value_unit": "count" if kind == "distribution" else "minor_units",
                "rows": selected,
            }
        )
    return {
        "kind": kind,
        "series": series,
        "metadata": metadata,
        "unit": "count" if kind == "distribution" else "original currency minor units",
    }
