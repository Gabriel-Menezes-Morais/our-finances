"""Validated, bounded report definitions and deterministic local pivot results."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.metrics import aggregate
from app.analytics.query import AnalyticsFilters, facts

Dimension = Literal[
    "currency",
    "date",
    "month",
    "year",
    "category_id",
    "category",
    "area_id",
    "project_id",
    "account_id",
    "responsible_id",
    "type",
    "status",
    "fixed",
    "essential",
    "variability",
    "necessity",
]
Metric = Literal[
    "expense_minor",
    "income_minor",
    "net_minor",
    "transaction_count",
    "expense_transaction_count",
    "allocation_count",
    "ticket_minor",
    "median_ticket_minor",
    "min_ticket_minor",
    "max_ticket_minor",
    "saving_rate",
    "expense_income_ratio",
]
ChartKind = Literal[
    "bar", "column", "line", "combination", "scatter", "waterfall", "heatmap", "doughnut", "pareto"
]


class ReportDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    name: str = Field(default="Análise", min_length=1, max_length=120)
    rows: list[Dimension] = Field(default=["category"], max_length=4)
    columns: list[Dimension] = Field(default=["month"], max_length=3)
    metrics: list[Metric] = Field(default=["expense_minor"], min_length=1, max_length=8)
    filters: AnalyticsFilters = Field(default_factory=AnalyticsFilters)
    chart: ChartKind = "column"
    sort_by: Dimension | Metric | None = None
    descending: bool = False
    max_cells: int = Field(default=10000, ge=1, le=100000)
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def unique_fields(self) -> ReportDefinition:
        dimensions = self.rows + self.columns
        if len(dimensions) != len(set(dimensions)) or len(self.metrics) != len(set(self.metrics)):
            raise ValueError("Report dimensions and metrics must be unique")
        if self.sort_by and self.sort_by not in dimensions + self.metrics:
            raise ValueError("sort_by must be an included dimension or metric")
        return self


def pivot(
    snapshot: dict[str, Any], definition: dict[str, Any] | ReportDefinition
) -> dict[str, Any]:
    report = (
        definition
        if isinstance(definition, ReportDefinition)
        else ReportDefinition.model_validate(definition)
    )
    rows, f = facts(snapshot, report.filters)
    # Currency is always a grouping key, even when omitted from the visible axes.
    dimensions = list(dict.fromkeys(["currency", *report.rows, *report.columns]))
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    row_keys, column_keys = set(), set()
    for row in rows:
        key = tuple(row.get(d) for d in dimensions)
        groups[key].append(row)
        row_keys.add(tuple(row.get(d) for d in ["currency", *report.rows]))
        column_keys.add(tuple(row.get(d) for d in report.columns))
    cell_count = len(row_keys) * max(1, len(column_keys)) * len(report.metrics)
    if cell_count > report.max_cells:
        raise ValueError("Report exceeds max_cells; narrow the period or filters")
    cells: list[dict[str, Any]] = []
    for key, grouped in sorted(
        groups.items(), key=lambda item: tuple(str(v or "") for v in item[0])
    ):
        metrics = aggregate(grouped)
        cells.append(
            {**dict(zip(dimensions, key, strict=True)), **{m: metrics[m] for m in report.metrics}}
        )
    if report.sort_by:
        key_name = report.sort_by
        from decimal import Decimal

        numeric = key_name in report.metrics
        cells.sort(
            key=lambda cell: (
                cell.get(key_name) is None,
                Decimal(str(cell[key_name]))
                if numeric and cell.get(key_name) is not None
                else str(cell.get(key_name, "")),
            ),
            reverse=report.descending,
        )
    totals: list[dict[str, Any]] = []
    for currency in sorted({r["currency"] for r in rows}):
        values = aggregate([r for r in rows if r["currency"] == currency])
        metric_values: dict[str, Any] = {m: values[m] for m in report.metrics}
        totals.append({"currency": currency, **metric_values})
    return {
        "definition": report.model_dump(mode="json"),
        "metadata": {
            "workspace_id": snapshot["workspace_id"],
            "revision": snapshot.get("revision", 0),
            "basis": f.basis,
            "grain": "allocations; distinct transaction metrics recomputed",
            "native_pivot_verified": False,
            "non_additive_metrics": [
                m
                for m in report.metrics
                if m not in {"expense_minor", "income_minor", "net_minor", "allocation_count"}
            ],
        },
        "dimensions": dimensions,
        "cells": cells,
        "totals_by_currency": totals,
        "cell_count": cell_count,
    }
