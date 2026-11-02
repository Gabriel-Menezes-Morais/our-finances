"""Authoritative integer-minor-unit aggregates and explicitly nullable ratios."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from app.analytics.query import (
    AnalyticsFilters,
    descendants,
    facts,
    financial_date,
    minor,
    validate_snapshot,
)


def ratio(numerator: int, denominator: int) -> str | None:
    return str(Decimal(numerator) / Decimal(denominator)) if denominator else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expense = sum(r["expense_minor"] for r in rows)
    income = sum(r["income_minor"] for r in rows)
    purchases: dict[str, int] = defaultdict(int)
    selected: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["type"] == "expense" and row["consumption"]:
            purchases[row["transaction_id"]] += row["amount_minor"]
        if row["consumption"] or row["type"] == "income":
            selected[row["transaction_id"]] += row["amount_minor"]
    amounts = list(purchases.values())
    count = len(purchases)
    average = ratio(sum(amounts), count)
    variance = (
        sum(((Decimal(v) - Decimal(average)) ** 2 for v in amounts), Decimal("0")) / count
        if count and average is not None
        else None
    )
    median_minor = str(median([Decimal(v) for v in amounts])) if amounts else None
    return {
        "expense_minor": expense,
        "income_minor": income,
        "net_minor": income - expense,
        "transaction_count": len(selected),
        "expense_transaction_count": count,
        "allocation_count": len(rows),
        "ticket_minor": average,
        "median_ticket_minor": median_minor,
        "min_ticket_minor": min(amounts) if amounts else None,
        "max_ticket_minor": max(amounts) if amounts else None,
        "population_variance_minor_squared": str(variance) if variance is not None else None,
        "population_stddev_minor": str(variance.sqrt()) if variance is not None else None,
        "saving_rate": ratio(income - expense, income),
        "expense_income_ratio": ratio(expense, income),
    }


def _group(rows: list[dict[str, Any]], dimensions: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(d) for d in dimensions)].append(row)
    return [
        {**dict(zip(dimensions, key, strict=True)), **aggregate(values)}
        for key, values in sorted(
            grouped.items(), key=lambda item: tuple(str(v or "") for v in item[0])
        )
    ]


def _period(snapshot: dict[str, Any], f: AnalyticsFilters) -> tuple[date | None, date | None]:
    dates = [
        date.fromisoformat(day)
        for t in snapshot.get("transactions", [])
        if (day := financial_date(t, f.basis))
    ]
    return f.start_date or (min(dates) if dates else None), (
        f.end_date - timedelta(days=1)
    ) if f.end_date else (max(dates) if dates else None)


def _monthly(
    rows: list[dict[str, Any]], start: date | None, end: date | None
) -> list[dict[str, Any]]:
    values = {(r["currency"], r["month"]): r for r in _group(rows, ("currency", "month"))}
    if start and end:
        month = start.replace(day=1)
        while month <= end:
            for currency in {r["currency"] for r in rows}:
                values.setdefault(
                    (currency, month.isoformat()[:7]),
                    {"currency": currency, "month": month.isoformat()[:7], **aggregate([])},
                )
            month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    result = []
    history: dict[str, list[int]] = defaultdict(list)
    cumulative: dict[tuple[str, str], int] = defaultdict(int)
    for (currency, month), row in sorted(values.items()):
        previous = history[currency][-1] if history[currency] else None
        last_year = values.get((currency, f"{int(month[:4]) - 1}{month[4:]}"))
        history[currency].append(row["expense_minor"])
        year_key = (currency, month[:4])
        cumulative[year_key] += row["expense_minor"]
        month_start = date.fromisoformat(month + "-01")
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
            days=1
        )
        result.append(
            {
                **row,
                "previous_month_expense_minor": previous,
                "month_change_rate": ratio(row["expense_minor"] - previous, previous)
                if previous is not None
                else None,
                "year_change_rate": ratio(
                    row["expense_minor"] - last_year["expense_minor"], last_year["expense_minor"]
                )
                if last_year
                else None,
                "rolling_3_month_mean_minor": ratio(sum(history[currency][-3:]), 3)
                if len(history[currency]) >= 3
                else None,
                "rolling_3_month_median_minor": str(median(history[currency][-3:]))
                if len(history[currency]) >= 3
                else None,
                "ytd_expense_minor": cumulative[year_key],
                "ytd_partial_population": bool(start and start > date(month_start.year, 1, 1)),
                "incomplete_period": bool(start and start > month_start or end and end < month_end),
                "history_months": len(history[currency]),
            }
        )
    return result


def _budgets(snapshot: dict[str, Any], f: AnalyticsFilters) -> list[dict[str, Any]]:
    from app.analytics.forecast import add_period

    result: list[dict[str, Any]] = []
    report_start, report_end = _period(snapshot, f)
    as_of_text = snapshot.get("as_of") or str(snapshot.get("generated_at", ""))[:10]
    as_of = date.fromisoformat(as_of_text) if as_of_text else report_end
    report_end = (f.end_date - timedelta(days=1)) if f.end_date else as_of or report_end
    if report_end is None:
        return result
    for budget in snapshot.get("budgets", []):
        if budget.get("active") is False:
            continue
        definition = f.model_dump(mode="json", exclude_none=True)
        definition["basis"] = "cash" if budget.get("basis") == "cash" else "competence"
        # Calculate prior complete periods with the same dimensional population for
        # carryover, then expose only periods intersecting the requested date window.
        definition.pop("start_date", None)
        definition.pop("end_date", None)
        selected, _ = facts(snapshot, definition)
        category_ids = (
            descendants(snapshot.get("categories", []), [budget["category_id"]])
            if budget.get("category_id")
            else None
        )
        selected = [
            r
            for r in selected
            if (category_ids is None or r["category_id"] in category_ids)
            and all(
                not budget.get(k) or r.get(k) == budget[k]
                for k in ("area_id", "project_id", "responsible_id")
            )
            and r["currency"] == budget.get("currency", snapshot.get("currency", "BRL"))
        ]
        # The effective budget and carryover retain the complete budget population;
        # narrowing a display filter cannot create extra available money.
        full_population, _ = facts(snapshot, {"basis": definition["basis"]})
        full_population = [
            r
            for r in full_population
            if (category_ids is None or r["category_id"] in category_ids)
            and all(
                not budget.get(k) or r.get(k) == budget[k]
                for k in ("area_id", "project_id", "responsible_id")
            )
            and r["currency"] == budget.get("currency", snapshot.get("currency", "BRL"))
        ]
        base_limit = budget.get("amount_minor", budget.get("limit_minor"))
        if base_limit is not None:
            base_limit = minor(base_limit)
        start = (
            date.fromisoformat(budget["start_date"])
            if budget.get("start_date")
            else (report_start or report_end)
        )
        anchor_day = start.day
        period = budget.get("period", "month")
        carry = 0
        for _ in range(1200):
            if start > report_end:
                break
            if period == "custom":
                end = date.fromisoformat(budget["end_date"]) - timedelta(days=1)
            else:
                following = add_period(start, period, 1, anchor_day)
                end = following - timedelta(days=1)
                if budget.get("end_date"):
                    end = min(end, date.fromisoformat(budget["end_date"]) - timedelta(days=1))
            if end < start:
                break
            full_actual = sum(
                r["expense_minor"]
                for r in full_population
                if start.isoformat() <= r["date"] <= min(end, report_end).isoformat()
            )
            limit = base_limit + carry if base_limit is not None else None
            if report_start is None or end >= report_start:
                window_start = max(start, report_start) if report_start else start
                window_end = min(end, report_end)
                actual = sum(
                    r["expense_minor"]
                    for r in selected
                    if window_start.isoformat() <= r["date"] <= window_end.isoformat()
                )
                elapsed_end = min(window_end, as_of) if as_of else window_end
                days = max(0, (elapsed_end - window_start).days + 1)
                thresholds = [
                    str(v)
                    for v in budget.get("thresholds", [])
                    if limit is not None and full_actual >= Decimal(str(v)) * limit
                ]
                projected = ratio(actual * ((end - start).days + 1), days) if days else None
                result.append(
                    {
                        "id": budget["id"],
                        "name": budget.get("name", "Orçamento"),
                        "currency": budget.get("currency", snapshot.get("currency", "BRL")),
                        "period": period,
                        "basis": definition["basis"],
                        "start_date": start.isoformat(),
                        "end_date": (end + timedelta(days=1)).isoformat(),
                        "filtered_start_date": window_start.isoformat(),
                        "filtered_end_date": (window_end + timedelta(days=1)).isoformat(),
                        "base_limit_minor": base_limit,
                        "limit_minor": limit,
                        "actual_minor": actual,
                        "budget_actual_minor": full_actual,
                        "remaining_minor": limit - full_actual if limit is not None else None,
                        "deviation_minor": full_actual - limit if limit is not None else None,
                        "consumed_rate": ratio(full_actual, limit) if limit is not None else None,
                        "zero_limit": limit == 0,
                        "no_limit": limit is None,
                        "thresholds_reached": thresholds,
                        "daily_expense_minor": ratio(actual, days) if days else None,
                        "projected_expense_minor": projected,
                        "projected_overrun": Decimal(projected) > limit
                        if projected is not None and limit is not None
                        else None,
                        "carryover_requested": bool(budget.get("carryover")),
                        "carryover_applied_minor": carry,
                        "coverage_note": "Filtered subperiod; full period limit retained"
                        if window_start != start or window_end != end
                        else None,
                    }
                )
            carry = limit - full_actual if budget.get("carryover") and limit is not None else 0
            if (
                period == "custom"
                or budget.get("end_date")
                and end >= date.fromisoformat(budget["end_date"]) - timedelta(days=1)
            ):
                break
            start = following
        else:
            raise ValueError("Budget period range exceeds 1200 periods")
    result.sort(key=lambda row: (row["currency"], row["start_date"], str(row["id"])))
    return result


def _balances(snapshot: dict[str, Any], end: date | None) -> list[dict[str, Any]]:
    result = []
    for account in snapshot.get("accounts", []):
        opening = account.get("opening_balance_minor", account.get("initial_balance_minor"))
        opening_day = account.get("opening_date", account.get("initial_balance_date"))
        if opening_day and end and str(opening_day)[:10] > end.isoformat():
            opening = None
        change = 0
        for tx in snapshot.get("transactions", []):
            if tx.get("status") == "cancelled" or not tx.get("settlement_date"):
                continue
            day = str(tx["settlement_date"])[:10]
            if end and day > end.isoformat() or opening_day and day < str(opening_day):
                continue
            if tx.get("currency", snapshot.get("currency")) != account.get(
                "currency", snapshot.get("currency")
            ):
                continue
            amount = minor(tx["amount_minor"])
            if tx.get("account_id") == account["id"]:
                change += amount if tx["type"] in {"income", "refund"} else -amount
            if tx["type"] == "transfer" and tx.get("to_account_id") == account["id"]:
                change += amount
        result.append(
            {
                "account_id": account["id"],
                "name": account.get("name"),
                "currency": account.get("currency", snapshot.get("currency")),
                "opening_balance_minor": opening,
                "recorded_change_minor": change,
                "balance_minor": minor(opening) + change if opening is not None else None,
                "coverage": "known_opening_balance"
                if opening is not None
                else "opening_balance_unknown",
            }
        )
    return result


def _goals(snapshot: dict[str, Any], end: date | None) -> list[dict[str, Any]]:
    result = []
    for goal in snapshot.get("goals", []):
        currency = goal.get("currency", snapshot.get("currency"))
        saved = sum(
            minor(c["amount_minor"])
            for c in snapshot.get("contributions", [])
            if c.get("goal_id") == goal["id"]
            and c.get("active") is not False
            and c.get("currency", currency) == currency
            and (not end or str(c["occurrence_date"])[:10] <= end.isoformat())
        )
        target = goal.get("target_minor")
        remaining = max(0, minor(target) - saved) if target is not None else None
        deadline = goal.get("deadline")
        days = (date.fromisoformat(deadline) - end).days if deadline and end else None
        result.append(
            {
                "id": goal["id"],
                "name": goal.get("name"),
                "currency": currency,
                "target_minor": target,
                "contributed_minor": saved,
                "remaining_minor": remaining,
                "progress_rate": ratio(saved, target) if target is not None else None,
                "deadline": deadline,
                "required_daily_minor": ratio(remaining, days)
                if remaining is not None and days is not None and days > 0
                else None,
            }
        )
    return result


def compute(snapshot: dict[str, Any], filters: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(snapshot)
    rows, f = facts(snapshot, filters)
    start, end = _period(snapshot, f)
    totals = _group(rows, ("currency",))
    categories = _group(rows, ("currency", "category_id", "category"))
    categories.sort(key=lambda r: (r["currency"], -r["expense_minor"], str(r["category_id"])))
    cumulative: dict[str, int] = defaultdict(int)
    total_map = {r["currency"]: r for r in totals}
    ranks: dict[str, int] = defaultdict(int)
    for row in categories:
        currency = row["currency"]
        ranks[currency] += 1
        cumulative[currency] += row["expense_minor"]
        denominator = total_map[currency]["expense_minor"]
        row.update(
            rank=ranks[currency],
            share=ratio(row["expense_minor"], denominator),
            pareto_cumulative_rate=ratio(cumulative[currency], denominator),
        )
    anomalies = []
    distributions = []
    for currency in total_map:
        purchases: dict[str, int] = defaultdict(int)
        for row in rows:
            if row["currency"] == currency and row["type"] == "expense" and row["consumption"]:
                purchases[row["transaction_id"]] += row["amount_minor"]
        if purchases:
            low, high = min(purchases.values()), max(purchases.values())
            width = max(1, (high - low + 10) // 10)
            for left in range(low, high + 1, width):
                right = min(high, left + width - 1)
                distributions.append(
                    {
                        "currency": currency,
                        "min_minor": left,
                        "max_minor": right,
                        "count": sum(left <= amount <= right for amount in purchases.values()),
                    }
                )
        if len(purchases) >= 5:
            center = median([Decimal(v) for v in purchases.values()])
            mad = Decimal(median([abs(Decimal(v) - center) for v in purchases.values()]))
            for tx_id, value in purchases.items():
                if Decimal(value) > center and (
                    Decimal(value) - center > 3 * mad if mad else Decimal(value) > 3 * center
                ):
                    anomalies.append(
                        {
                            "transaction_id": tx_id,
                            "currency": currency,
                            "amount_minor": value,
                            "median_minor": str(center),
                            "median_absolute_deviation_minor": str(mad),
                            "rule": "above median + 3 MAD; when MAD=0, above 3x median",
                            "interpretation": "Review signal; not evidence of fraud or error",
                        }
                    )
    return {
        "metadata": {
            "workspace_id": snapshot["workspace_id"],
            "revision": snapshot.get("revision", 0),
            "currency_conversion": "none",
            "timezone": snapshot.get("timezone", "America/Sao_Paulo"),
            "basis": f.basis,
            "start_date": start.isoformat() if start else None,
            "end_date": (end + timedelta(days=1)).isoformat() if end else None,
            "end_date_inclusive": end.isoformat() if end else None,
            "period_interval": "[start_date, end_date)",
            "filters": f.model_dump(mode="json", exclude_none=True),
            "source": "domain_snapshot",
            "metric_version": 1,
            "population": (
                "filtered allocations; transaction counts distinct; "
                "ticket uses expense purchases, refunds reduce net expense"
            ),
        },
        "totals_by_currency": totals,
        "categories": categories,
        "areas": _group(rows, ("currency", "area_id")),
        "projects": _group(rows, ("currency", "project_id")),
        "daily": _group(rows, ("currency", "date")),
        "monthly": _monthly(rows, start, end),
        "annual": _group(rows, ("currency", "year")),
        "classifications": _group(rows, ("currency", "variability", "necessity")),
        "budgets": _budgets(snapshot, f),
        "balances": _balances(snapshot, end),
        "goals": _goals(snapshot, end),
        "anomalies": anomalies,
        "distributions": distributions,
        "coverage": {
            "transaction_count": len({r["transaction_id"] for r in rows}),
            "allocation_count": len(rows),
            "history_start": start.isoformat() if start else None,
            "history_end": end.isoformat() if end else None,
            "empty": not rows,
        },
    }
