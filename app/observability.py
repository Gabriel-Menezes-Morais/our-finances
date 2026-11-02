"""Bounded structured events without request bodies, credentials or SQL errors."""

import json
from datetime import UTC, datetime
from typing import Any

ALLOWED = {
    "correlation_id",
    "duration_ms",
    "revision",
    "attempts",
    "reason",
    "provider",
    "status_code",
}


def event(name: str, state: str, **fields: Any) -> None:
    payload = {
        "message": name,
        "state": state,
        "timestamp": datetime.now(UTC).isoformat(),
        **{key: value for key, value in fields.items() if key in ALLOWED},
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
