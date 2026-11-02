"""Data-only revisioned payload, with no fabricated connector success."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.analytics.metrics import compute
from app.analytics.query import facts, validate_snapshot


def build_projection(
    snapshot: dict[str, Any], filters: dict[str, Any] | None = None
) -> dict[str, Any]:
    validate_snapshot(snapshot)
    rows, _ = facts(snapshot, filters)
    analytics = compute(snapshot, filters)
    selected_ids = {r["transaction_id"] for r in rows}
    tables = {
        "transactions": [
            t for t in snapshot.get("transactions", []) if str(t["id"]) in selected_ids
        ],
        "allocations": rows,
        "categories": snapshot.get("categories", []),
        "accounts": snapshot.get("accounts", []),
        "budgets": analytics["budgets"],
        "monthly": analytics["monthly"],
        "annual": analytics["annual"],
        "goals": analytics["goals"],
    }
    digest = hashlib.sha256(
        json.dumps(
            tables, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "workspace_id": snapshot["workspace_id"],
        "revision": snapshot.get("revision", 0),
        "generated_at": snapshot.get("generated_at"),
        "data_hash": digest,
        "metadata": analytics["metadata"],
        "tables": tables,
        "checks": analytics["totals_by_currency"],
        "publication_status": "local_projection_only",
        "native_objects_verified": False,
        "preserve_manual_sheets": True,
    }
