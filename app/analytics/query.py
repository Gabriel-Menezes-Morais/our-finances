"""Closed filters and allocation-grain facts; never executes caller code or SQL."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class AnalyticsFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date | None = None
    end_date: date | None = None
    basis: Literal["competence", "occurrence", "cash"] = "competence"
    category_ids: list[str] | None = None
    area_ids: list[str] | None = None
    project_ids: list[str] | None = None
    account_ids: list[str] | None = None
    responsible_ids: list[str] | None = None
    tag_ids: list[str] | None = None
    types: list[Literal["income", "expense", "refund", "transfer"]] | None = None
    statuses: list[str] | None = None
    currencies: list[str] | None = None

    @model_validator(mode="after")
    def valid_period(self) -> AnalyticsFilters:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must precede end_date")
        return self


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if not snapshot.get("workspace_id"):
        raise ValueError("An authorized workspace snapshot is required")
    for collection in snapshot.values():
        if isinstance(collection, list):
            for row in collection:
                if (
                    isinstance(row, dict)
                    and row.get("workspace_id", snapshot["workspace_id"])
                    != snapshot["workspace_id"]
                ):
                    raise ValueError("Snapshot contains another workspace")


def minor(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Amounts must be integer minor units")
    return int(value)


def descendants(categories: list[dict[str, Any]], selected: list[str]) -> set[str]:
    result = set(selected)
    while True:
        expanded = result | {str(c["id"]) for c in categories if c.get("parent_id") in result}
        if result == expanded:
            return result
        result = expanded


def is_consumption(tx: dict[str, Any]) -> bool:
    return (
        tx.get("type") in {"expense", "refund"}
        and not tx.get("is_card_settlement", False)
        and tx.get("kind") not in {"card_payment", "card_settlement"}
    )


def financial_date(tx: dict[str, Any], basis: str) -> str | None:
    key = {
        "competence": "competence_date",
        "occurrence": "occurrence_date",
        "cash": "settlement_date",
    }[basis]
    value = tx.get(key)
    if value is None and basis != "cash":
        value = tx.get("occurrence_date")
    return str(value)[:10] if value else None


def _cash_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Card consumption follows actual linked payments, not purchase booking."""
    txs = {str(t["id"]): t for t in snapshot.get("transactions", [])}
    cards = {a["id"] for a in snapshot.get("accounts", []) if a.get("type") == "card"}
    allocations: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot.get("allocations", []):
        allocations.setdefault(str(row.get("transaction_id", row.get("tx_id"))), []).append(row)
    result = [
        tx
        for tx in txs.values()
        if not (tx.get("type") in {"expense", "refund"} and tx.get("account_id") in cards)
    ]
    for installment in snapshot.get("installments", []):
        tx = txs.get(str(installment["transaction_id"]))
        if (
            not tx
            or tx.get("account_id") not in cards
            or installment.get("active") is False
            or tx.get("status") == "cancelled"
        ):
            continue
        original = minor(tx["amount_minor"])
        original_allocations = allocations.get(str(tx["id"])) or [
            {"category_id": tx.get("category_id"), "amount_minor": original}
        ]
        if sum(minor(a["amount_minor"]) for a in original_allocations) != original:
            raise ValueError("Cash purchase allocations do not reconcile")
        for index, payment in enumerate(installment.get("payments", [])):
            settlement = txs.get(str(payment["transaction_id"]))
            if not settlement or settlement.get("status") == "cancelled":
                continue
            day = settlement.get("settlement_date")
            if not day:
                continue
            amount = minor(payment["amount_minor"])
            remaining = amount
            parts = []
            for position, allocation in enumerate(original_allocations):
                share = amount * minor(allocation["amount_minor"]) // original if original else 0
                if position == len(original_allocations) - 1:
                    share = remaining
                remaining -= share
                if share == 0:
                    continue
                parts.append(
                    {
                        **allocation,
                        "amount_minor": share,
                        "id": f"cash:{installment['id']}:{index}:{position}",
                    }
                )
            result.append(
                {
                    **tx,
                    "id": f"cash:{installment['id']}:{index}",
                    "_transaction_id": str(tx["id"]),
                    "_cash_account_id": settlement.get("account_id"),
                    "_cash_allocations": parts,
                    "amount_minor": amount,
                    "settlement_date": day,
                    "status": "settled",
                }
            )
    return result


def facts(
    snapshot: dict[str, Any], filters: dict[str, Any] | AnalyticsFilters | None = None
) -> tuple[list[dict[str, Any]], AnalyticsFilters]:
    """Return one row per allocation, with original transaction amount kept separate.

    Transfers remain queryable but have zero consumption/income. A transaction without
    allocations receives one synthetic fact, allowing uncategorized amounts to reconcile.
    """
    validate_snapshot(snapshot)
    f = (
        filters
        if isinstance(filters, AnalyticsFilters)
        else AnalyticsFilters.model_validate(filters or {})
    )
    categories = {str(c["id"]): c for c in snapshot.get("categories", [])}
    source_transactions = (
        _cash_rows(snapshot) if f.basis == "cash" else snapshot.get("transactions", [])
    )
    txs = {str(t["id"]): t for t in source_transactions}
    by_tx: dict[str, list[dict[str, Any]]] = {}
    for allocation in snapshot.get("allocations", []):
        by_tx.setdefault(str(allocation.get("transaction_id", allocation.get("tx_id"))), []).append(
            allocation
        )
    selected_categories = (
        descendants(list(categories.values()), f.category_ids)
        if f.category_ids is not None
        else None
    )
    result = []
    for tx_id, tx in sorted(txs.items()):
        if tx.get("status") in {"cancelled", "canceled", "deleted", "void"} or tx.get("deleted_at"):
            continue
        day = financial_date(tx, f.basis)
        if not day:
            continue
        parsed = date.fromisoformat(day)
        if f.start_date and parsed < f.start_date or f.end_date and parsed >= f.end_date:
            continue
        currency = tx.get("currency", snapshot.get("currency", "BRL"))
        checks = [
            (f.types, tx.get("type")),
            (f.statuses, tx.get("status")),
            (f.currencies, currency),
            (f.responsible_ids, tx.get("responsible_id")),
        ]
        if any(allowed is not None and value not in allowed for allowed, value in checks):
            continue
        accounts = {
            tx.get("account_id"),
            tx.get("from_account_id"),
            tx.get("to_account_id"),
            tx.get("destination_account_id"),
            tx.get("_cash_account_id"),
        }
        if f.account_ids is not None and not accounts.intersection(f.account_ids):
            continue
        tags = tx.get("tag_ids", tx.get("tags", [])) or []
        if f.tag_ids is not None and not set(tags).intersection(f.tag_ids):
            continue
        amount = minor(tx["amount_minor"])
        allocations = (
            tx.get("_cash_allocations")
            or by_tx.get(tx_id)
            or [
                {
                    "id": f"unallocated:{tx_id}",
                    "category_id": tx.get("category_id"),
                    "project_id": tx.get("project_id"),
                    "amount_minor": amount,
                }
            ]
        )
        if sum(minor(a["amount_minor"]) for a in allocations) != amount:
            raise ValueError("Allocations do not reconcile to transaction")
        for allocation in allocations:
            category_id = allocation.get("category_id")
            category = dict(categories.get(str(category_id), {}))
            ancestor = category
            visited: set[str] = set()
            while ancestor.get("parent_id") and ancestor["parent_id"] not in visited:
                visited.add(ancestor["parent_id"])
                ancestor = categories.get(str(ancestor["parent_id"]), {})
                for inherited in ("area_id", "variability", "necessity"):
                    if category.get(inherited) is None and ancestor.get(inherited) is not None:
                        category[inherited] = ancestor[inherited]
            area_id = allocation.get("area_id") or category.get("area_id") or tx.get("area_id")
            project_id = allocation.get("project_id") or tx.get("project_id")
            if selected_categories is not None and category_id not in selected_categories:
                continue
            if f.area_ids is not None and area_id not in f.area_ids:
                continue
            if f.project_ids is not None and project_id not in f.project_ids:
                continue
            allocated = minor(allocation["amount_minor"])
            expense = (
                allocated * (-1 if tx.get("type") == "refund" else 1) if is_consumption(tx) else 0
            )
            income = allocated if tx.get("type") == "income" else 0
            result.append(
                {
                    "transaction_id": tx.get("_transaction_id", tx_id),
                    "allocation_id": str(allocation.get("id", "")),
                    "date": day,
                    "month": day[:7],
                    "year": day[:4],
                    "currency": currency,
                    "type": tx.get("type"),
                    "status": tx.get("status"),
                    "account_id": tx.get("_cash_account_id")
                    or tx.get("account_id", tx.get("from_account_id")),
                    "purchase_account_id": tx.get("account_id"),
                    "responsible_id": tx.get("responsible_id"),
                    "category_id": category_id,
                    "category": category.get("name", "Sem categoria"),
                    "area_id": area_id,
                    "project_id": project_id,
                    "expense_minor": expense,
                    "income_minor": income,
                    "net_minor": income - expense,
                    "amount_minor": allocated,
                    "transaction_amount_minor": amount,
                    "consumption": is_consumption(tx),
                    "fixed": category.get("fixed"),
                    "essential": category.get("essential"),
                    "variability": tx.get("variability") or category.get("variability"),
                    "necessity": tx.get("necessity") or category.get("necessity"),
                }
            )
    return result, f
