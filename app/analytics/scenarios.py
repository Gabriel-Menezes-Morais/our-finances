"""Scenarios adjust scheduled projections, never the underlying snapshot."""

from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.forecast import ForecastAssumptions, forecast
from app.analytics.query import descendants, minor


class ExtraExpense(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str
    amount_minor: int = Field(ge=0, strict=True)
    currency: str
    description: str = "Despesa extraordinária"


class ScenarioAssumptions(ForecastAssumptions):
    name: str = Field(default="Cenário", max_length=120)
    income_change_rate: Decimal = Decimal("0")
    income_minor: int | None = Field(default=None, ge=0, strict=True)
    extra_expenses_minor: int = Field(default=0, ge=0, strict=True)
    category_reductions: dict[str, Decimal] = Field(default_factory=dict)
    extraordinary_expenses: list[ExtraExpense] = Field(default_factory=list, max_length=1000)


def scenario(snapshot: dict[str, Any], assumptions: dict[str, Any]) -> dict[str, Any]:
    a = ScenarioAssumptions.model_validate(assumptions)
    if a.income_minor is not None and a.income_change_rate != 0:
        raise ValueError("Choose absolute monthly income or a relative income change")
    if not a.income_change_rate.is_finite() or a.income_change_rate < -1:
        raise ValueError("Income change must be finite and >= -1")
    if any(not rate.is_finite() or not 0 <= rate <= 1 for rate in a.category_reductions.values()):
        raise ValueError("Category reduction rates must be between 0 and 1")
    base_args = a.model_dump(mode="json", include=set(ForecastAssumptions.model_fields))
    baseline = forecast(snapshot, base_args)
    projected = deepcopy(baseline)
    reductions = {
        category: descendants(snapshot.get("categories", []), [category])
        for category in a.category_reductions
    }
    adjustments = []
    for row in projected["items"]:
        before = row["amount_minor"]
        rate = a.income_change_rate if row["type"] == "income" else Decimal("0")
        amount = int((Decimal(before) * (1 + rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if row["type"] == "expense":
            amount = 0
            for allocation in row["category_allocations"]:
                applicable = [
                    a.category_reductions[k]
                    for k, children in reductions.items()
                    if allocation.get("category_id") in children
                ]
                # Parent/child overlaps apply the greatest requested reduction once.
                rate = -max(applicable) if applicable else Decimal("0")
                adjusted = int(
                    (Decimal(allocation["amount_minor"]) * (1 + rate)).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )
                allocation["amount_minor"] = adjusted
                amount += adjusted
        row["amount_minor"] = amount
        row["expense_minor"] = (
            amount if row["type"] == "expense" else -amount if row["type"] == "refund" else 0
        )
        row["income_minor"] = amount if row["type"] == "income" else 0
        row["net_minor"] = row["income_minor"] - row["expense_minor"]
        if before != amount:
            adjustments.append(
                {
                    "id": row["id"],
                    "before_minor": before,
                    "after_minor": amount,
                    "delta_minor": amount - before,
                    "applied_rate": str(a.income_change_rate)
                    if row["type"] == "income"
                    else "per_category_allocation",
                    "currency": row["currency"],
                }
            )
    start = baseline["metadata"]["start_date"]
    end = baseline["metadata"]["end_date"]
    for index, extra in enumerate(a.extraordinary_expenses):
        day = date.fromisoformat(extra.date).isoformat()
        if not start <= day < end:
            raise ValueError("Extraordinary expense must be inside the scenario period")
        amount = minor(extra.amount_minor)
        projected["items"].append(
            {
                "id": f"extra:{index}",
                "source": "scenario",
                "date": day,
                "currency": extra.currency,
                "type": "expense",
                "amount_minor": amount,
                "expense_minor": amount,
                "income_minor": 0,
                "net_minor": -amount,
                "description": extra.description,
                "consumption_actual": False,
            }
        )
        adjustments.append(
            {
                "id": f"extra:{index}",
                "before_minor": 0,
                "after_minor": amount,
                "delta_minor": amount,
                "currency": extra.currency,
            }
        )
    projected["items"].sort(key=lambda r: (r["date"], r["currency"], r["id"]))
    currencies = {r["currency"] for r in projected["items"]} | {
        r["currency"] for r in baseline["totals_by_currency"]
    }
    projected["totals_by_currency"] = []
    projected["monthly"] = []
    for currency in sorted(currencies):
        rows = [r for r in projected["items"] if r["currency"] == currency]
        opening = next(
            (
                r["opening_balance_minor"]
                for r in baseline["totals_by_currency"]
                if r["currency"] == currency
            ),
            None,
        )
        baseline_total: dict[str, Any] = next(
            (r for r in baseline["totals_by_currency"] if r["currency"] == currency), {}
        )
        transfer_delta = baseline_total.get("transfer_delta_minor", 0)
        net = sum(r["net_minor"] for r in rows)
        projected["totals_by_currency"].append(
            {
                "currency": currency,
                "income_minor": sum(r["income_minor"] for r in rows),
                "expense_minor": sum(r["expense_minor"] for r in rows),
                "net_minor": net,
                "opening_balance_minor": opening,
                "closing_balance_minor": opening + net + transfer_delta
                if opening is not None and not baseline_total.get("partial_population", False)
                else None,
                "transfer_delta_minor": transfer_delta,
            }
        )
        for month in sorted({r["date"][:7] for r in rows}):
            selected = [r for r in rows if r["date"][:7] == month]
            projected["monthly"].append(
                {
                    "currency": currency,
                    "month": month,
                    "income_minor": sum(r["income_minor"] for r in selected),
                    "expense_minor": sum(r["expense_minor"] for r in selected),
                    "net_minor": sum(r["net_minor"] for r in selected),
                }
            )
    projected["metadata"]["assumptions"] = a.model_dump(mode="json")
    projected["metadata"]["basis"] = "scenario"
    monthly_adjustments = []
    undated_adjustments = []
    currency = snapshot.get("currency", "BRL")
    if a.income_minor is not None or a.extra_expenses_minor:
        total = next(
            (r for r in projected["totals_by_currency"] if r["currency"] == currency), None
        )
        if total is None:
            total = {
                "currency": currency,
                "income_minor": 0,
                "expense_minor": 0,
                "net_minor": 0,
                "opening_balance_minor": None,
                "closing_balance_minor": None,
            }
            projected["totals_by_currency"].append(total)
        if a.income_minor is not None:
            month = date.fromisoformat(start).replace(day=1)
            exclusive_end = date.fromisoformat(end)
            while month < exclusive_end:
                following = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
                covered_days = (
                    min(following, exclusive_end) - max(month, date.fromisoformat(start))
                ).days
                target = int(
                    (
                        Decimal(a.income_minor)
                        * covered_days
                        / calendar.monthrange(month.year, month.month)[1]
                    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
                label = month.isoformat()[:7]
                monthly = next(
                    (
                        r
                        for r in projected["monthly"]
                        if r["currency"] == currency and r["month"] == label
                    ),
                    None,
                )
                if monthly is None:
                    monthly = {
                        "currency": currency,
                        "month": label,
                        "income_minor": 0,
                        "expense_minor": 0,
                        "net_minor": 0,
                    }
                    projected["monthly"].append(monthly)
                delta = target - monthly["income_minor"]
                monthly_adjustments.append(
                    {
                        "currency": currency,
                        "month": label,
                        "income_before_minor": monthly["income_minor"],
                        "income_after_minor": target,
                        "income_delta_minor": delta,
                        "covered_calendar_days": covered_days,
                        "date": None,
                        "premise": (
                            "absolute monthly income prorated by covered calendar days; "
                            "cash receipt date unknown"
                        ),
                    }
                )
                monthly["income_minor"] = target
                monthly["net_minor"] += delta
                total["income_minor"] += delta
                total["net_minor"] += delta
                month = following
        if a.extra_expenses_minor:
            total["expense_minor"] += a.extra_expenses_minor
            total["net_minor"] -= a.extra_expenses_minor
            undated_adjustments.append(
                {
                    "currency": currency,
                    "expense_minor": a.extra_expenses_minor,
                    "date": None,
                    "premise": "aggregate extraordinary expense; no cash date supplied",
                }
            )
        total["closing_balance_minor"] = None
        total["coverage"] = "monthly/undated scenario premises; cash closing cannot be inferred"
        projected["metadata"]["cash_timing_complete"] = False
    projected["monthly"].sort(key=lambda r: (r["currency"], r["month"]))
    return {
        "name": a.name,
        "baseline": baseline,
        "projected": projected,
        "adjustments": adjustments,
        "monthly_adjustments": monthly_adjustments,
        "undated_adjustments": undated_adjustments,
        "assumptions": a.model_dump(mode="json"),
        "actuals_modified": False,
    }
