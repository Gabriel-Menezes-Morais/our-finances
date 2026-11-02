"""Scheduled cash commitments, informed wealth and explicitly supplied debt rates."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.metrics import _balances, ratio
from app.analytics.query import AnalyticsFilters, descendants, minor, validate_snapshot


class ForecastAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date | None = None
    end_date: date | None = None
    horizon_days: int = Field(default=90, ge=1, le=3660)
    include_recurrences: bool = True
    filters: AnalyticsFilters = Field(default_factory=AnalyticsFilters)
    debt_payment_minor: dict[str, int] = Field(default_factory=dict)
    debt_periods: int = Field(default=12, ge=1, le=600)

    @model_validator(mode="after")
    def valid_dates(self) -> ForecastAssumptions:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date precedes start_date")
        if any(isinstance(v, bool) or v < 0 for v in self.debt_payment_minor.values()):
            raise ValueError("Debt payments must be nonnegative minor units")
        return self


def add_period(day: date, frequency: str, interval: int, anchor_day: int | None = None) -> date:
    if frequency == "day":
        return day + timedelta(days=interval)
    if frequency == "week":
        return day + timedelta(weeks=interval)
    months = interval * (12 if frequency == "year" else 1)
    month_index = day.year * 12 + day.month - 1 + months
    year, month = divmod(month_index, 12)
    return date(
        year, month + 1, min(anchor_day or day.day, calendar.monthrange(year, month + 1)[1])
    )


def _wealth(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for kind in ("assets", "liabilities"):
        for row in snapshot.get(kind, []):
            if row.get("active") is False:
                continue
            currency = row.get("currency", snapshot.get("currency", "BRL"))
            group = grouped.setdefault(
                currency,
                {
                    "currency": currency,
                    "assets_minor": 0,
                    "liabilities_minor": 0,
                    "unknown_values": [],
                    "as_of_dates": [],
                },
            )
            if row.get("value_minor") is None:
                group["unknown_values"].append(row["id"])
            else:
                group[f"{kind}_minor"] += minor(row["value_minor"])
            if row.get("as_of"):
                group["as_of_dates"].append(row["as_of"])
    for group in grouped.values():
        group["net_worth_minor"] = (
            group["assets_minor"] - group["liabilities_minor"]
            if not group["unknown_values"]
            else None
        )
        group["coverage"] = (
            "informed_values_only" if not group["unknown_values"] else "incomplete_values"
        )
        group["as_of_dates"] = sorted(set(group["as_of_dates"]))
    return sorted(grouped.values(), key=lambda r: r["currency"])


def forecast(snapshot: dict[str, Any], assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(snapshot)
    a = ForecastAssumptions.model_validate(assumptions or {})
    as_of = snapshot.get("as_of") or str(snapshot.get("generated_at", ""))[:10]
    if a.start_date is None and a.filters.start_date is None and not as_of:
        raise ValueError("Forecast requires start_date or snapshot.as_of")
    start = a.start_date or a.filters.start_date or date.fromisoformat(as_of)
    end = a.end_date or a.filters.end_date or start + timedelta(days=a.horizon_days)
    if end < start or (end - start).days > 3660:
        raise ValueError("Forecast horizon must be between 0 and 3660 days")
    txs = {str(t["id"]): t for t in snapshot.get("transactions", [])}
    categories = {str(c["id"]): c for c in snapshot.get("categories", [])}
    selected_categories = (
        descendants(list(categories.values()), a.filters.category_ids)
        if a.filters.category_ids is not None
        else None
    )
    allocations_by_tx: dict[str, list[dict[str, Any]]] = {}
    for allocation in snapshot.get("allocations", []):
        allocations_by_tx.setdefault(
            str(allocation.get("transaction_id", allocation.get("tx_id"))), []
        ).append(allocation)
    items: list[dict[str, Any]] = []

    def append(identifier: str, source: str, day: str, row: dict[str, Any], amount: int) -> None:
        parsed = date.fromisoformat(day[:10])
        if not start <= parsed < end:
            return
        kind = row.get("type", "expense")
        currency = row.get("currency", snapshot.get("currency", "BRL"))
        checks = [
            (a.filters.types, kind),
            (a.filters.currencies, currency),
            (a.filters.responsible_ids, row.get("responsible_id")),
            (a.filters.statuses, row.get("status", "pending")),
        ]
        if any(allowed is not None and value not in allowed for allowed, value in checks):
            return
        if a.filters.account_ids is not None and not {
            row.get("account_id"),
            row.get("to_account_id"),
        }.intersection(a.filters.account_ids):
            return
        if a.filters.tag_ids is not None and not set(row.get("tags", [])).intersection(
            a.filters.tag_ids
        ):
            return
        allocations = (
            allocations_by_tx.get(str(row.get("id")))
            or row.get("allocations")
            or [
                {
                    "category_id": row.get("category_id"),
                    "amount_minor": minor(row.get("amount_minor", amount)),
                }
            ]
        )
        original_amount = sum(minor(a["amount_minor"]) for a in allocations)
        if original_amount != minor(row.get("amount_minor", amount)):
            raise ValueError("Forecast allocations must reconcile to the parent amount")
        weighted = []
        remaining = amount
        for index, allocation in enumerate(allocations):
            share = (
                amount * minor(allocation["amount_minor"]) // original_amount
                if original_amount
                else 0
            )
            if index == len(allocations) - 1:
                share = remaining
            remaining -= share
            if share == 0:
                continue
            category_id = allocation.get("category_id")
            area_id = (
                allocation.get("area_id")
                or categories.get(str(category_id), {}).get("area_id")
                or row.get("area_id")
            )
            project_id = allocation.get("project_id") or row.get("project_id")
            if selected_categories is not None and category_id not in selected_categories:
                continue
            if a.filters.area_ids is not None and area_id not in a.filters.area_ids:
                continue
            if a.filters.project_ids is not None and project_id not in a.filters.project_ids:
                continue
            weighted.append(
                {
                    "category_id": category_id,
                    "amount_minor": share,
                    "area_id": area_id,
                    "project_id": project_id,
                }
            )
        if not weighted:
            return
        amount = sum(w["amount_minor"] for w in weighted)
        items.append(
            {
                "id": identifier,
                "source": source,
                "date": parsed.isoformat(),
                "currency": row.get("currency", snapshot.get("currency", "BRL")),
                "type": kind,
                "amount_minor": amount,
                "income_minor": amount if kind == "income" else 0,
                "expense_minor": amount
                if kind == "expense"
                else -amount
                if kind == "refund"
                else 0,
                "net_minor": amount
                if kind in {"income", "refund"}
                else -amount
                if kind == "expense"
                else 0,
                "account_id": row.get("account_id"),
                "to_account_id": row.get("to_account_id"),
                "category_id": row.get("category_id"),
                "category_allocations": weighted,
                "consumption_actual": False,
                "description": row.get("description", row.get("name", "")),
            }
        )

    installment_parents = {str(i["transaction_id"]) for i in snapshot.get("installments", [])}
    for tx_id, tx in txs.items():
        if tx.get("status") == "pending" and tx_id not in installment_parents:
            day = tx.get("due_date") or tx.get("settlement_date") or tx.get("occurrence_date")
            if day:
                append(
                    f"transaction:{tx_id}",
                    "pending_transaction",
                    str(day),
                    tx,
                    minor(tx["amount_minor"]),
                )
    for installment in snapshot.get("installments", []):
        tx = txs.get(str(installment["transaction_id"]), {})
        if (
            installment.get("settled")
            or installment.get("active") is False
            or tx.get("status") == "cancelled"
        ):
            continue
        remaining = max(
            0,
            minor(installment["amount_minor"])
            - minor(installment.get("paid_minor", 0))
            - minor(installment.get("refunded_minor", 0)),
        )
        if not remaining:
            continue
        append(
            f"installment:{installment['id']}",
            "installment",
            installment["due_date"],
            tx,
            remaining,
        )
    if a.include_recurrences:
        materialized = {(t.get("recurrence_id"), t.get("recurrence_date")) for t in txs.values()}
        for recurrence in snapshot.get("recurrences", []):
            if recurrence.get("paused") or recurrence.get("active") is False:
                continue
            day = date.fromisoformat(recurrence["next_date"])
            anchor_day = recurrence.get("anchor_day", day.day)
            until = (
                min(end, date.fromisoformat(recurrence["end_date"]))
                if recurrence.get("end_date")
                else end
            )
            interval = recurrence.get("interval", 1)
            frequency = recurrence.get("frequency", "month")
            if (
                not isinstance(interval, int)
                or interval < 1
                or frequency not in {"day", "week", "month", "year"}
            ):
                raise ValueError("Invalid recurrence frequency/interval")
            template = recurrence.get("template", {})
            # next_date is the domain's first unmaterialized occurrence, preventing
            # duplication with already generated transactions when the domain advances it.
            while day <= until:
                if (
                    day.isoformat() not in recurrence.get("exceptions", [])
                    and (recurrence["id"], day.isoformat()) not in materialized
                ):
                    append(
                        f"recurrence:{recurrence['id']}:{day.isoformat()}",
                        "recurrence",
                        day.isoformat(),
                        template,
                        minor(template["amount_minor"]),
                    )
                day = add_period(day, frequency, interval, anchor_day)
    items.sort(key=lambda r: (r["date"], r["currency"], r["id"]))
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in items:
        key = (row["currency"], row["date"][:7])
        group = grouped.setdefault(
            key,
            {
                "currency": key[0],
                "month": key[1],
                "income_minor": 0,
                "expense_minor": 0,
                "net_minor": 0,
                "commitment_count": 0,
            },
        )
        for field in ("income_minor", "expense_minor", "net_minor"):
            group[field] += row[field]
        group["commitment_count"] += 1
    opening = _balances(snapshot, start - timedelta(days=1))
    liquid_ids = {
        account["id"]
        for account in snapshot.get("accounts", [])
        if account.get("type", "bank") in {"bank", "cash"}
    }
    opening = [r for r in opening if r["account_id"] in liquid_ids]
    if a.filters.account_ids is not None:
        opening = [r for r in opening if r["account_id"] in a.filters.account_ids]
    if a.filters.currencies is not None:
        opening = [r for r in opening if r["currency"] in a.filters.currencies]
    currencies = sorted({r["currency"] for r in items} | {r["currency"] for r in opening})
    totals = []
    for currency in currencies:
        selected = [r for r in items if r["currency"] == currency]
        accounts = [r for r in opening if r["currency"] == currency]
        partial_population = any(
            getattr(a.filters, field) is not None
            for field in (
                "category_ids",
                "area_ids",
                "project_ids",
                "responsible_ids",
                "tag_ids",
                "types",
                "statuses",
            )
        )
        known = bool(accounts) and all(r["balance_minor"] is not None for r in accounts)
        initial = sum(r["balance_minor"] for r in accounts) if known else None
        income = sum(r["income_minor"] for r in selected)
        expense = sum(r["expense_minor"] for r in selected)
        selected_accounts = {r["account_id"] for r in accounts}
        transfer_delta = sum(
            (r["amount_minor"] if r.get("to_account_id") in selected_accounts else 0)
            - (r["amount_minor"] if r.get("account_id") in selected_accounts else 0)
            for r in selected
            if r["type"] == "transfer"
        )
        totals.append(
            {
                "currency": currency,
                "opening_balance_minor": initial,
                "income_minor": income,
                "expense_minor": expense,
                "net_minor": income - expense,
                "transfer_delta_minor": transfer_delta,
                "closing_balance_minor": initial + income - expense + transfer_delta
                if initial is not None and not partial_population
                else None,
                "partial_population": partial_population,
                "commitment_income_ratio": ratio(expense, income),
                "coverage": "scheduled_items_only; no statistical trend or missing income inferred",
            }
        )
    debt = []
    for liability in snapshot.get("liabilities", []):
        if liability.get("active") is False:
            continue
        payment = a.debt_payment_minor.get(liability["id"])
        rate = liability.get("rate")
        balance = liability.get("value_minor")
        record: dict[str, Any] = {
            "liability_id": liability["id"],
            "currency": liability.get("currency", snapshot.get("currency")),
            "rate": rate,
            "rate_period": liability.get("rate_period"),
            "schedule": [],
        }
        if (
            rate is None
            or balance is None
            or payment is None
            or liability.get("rate_period") not in {"month", "year"}
        ):
            record["coverage"] = (
                "requires informed value, rate, rate_period (month/year) and explicit payment"
            )
        else:
            rate_decimal = Decimal(str(rate))
            if not rate_decimal.is_finite() or rate_decimal < 0:
                raise ValueError("Debt rate must be a finite nonnegative decimal")
            balance = minor(balance)
            for period in range(1, a.debt_periods + 1):
                interest = int(
                    (Decimal(balance) * rate_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
                paid = min(payment, balance + interest)
                balance += interest - paid
                record["schedule"].append(
                    {
                        "period": period,
                        "interest_minor": interest,
                        "payment_minor": paid,
                        "balance_minor": balance,
                    }
                )
                if balance == 0:
                    break
            record["coverage"] = "supplied_rate_and_payment; fixed periodic schedule"
        debt.append(record)
    return {
        "metadata": {
            "workspace_id": snapshot["workspace_id"],
            "revision": snapshot.get("revision", 0),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "basis": "scheduled_cash",
            "actuals_modified": False,
            "assumptions": a.model_dump(mode="json"),
        },
        "items": items,
        "monthly": [grouped[k] for k in sorted(grouped)],
        "totals_by_currency": totals,
        "balances": opening,
        "net_worth": _wealth(snapshot),
        "debts": debt,
    }
