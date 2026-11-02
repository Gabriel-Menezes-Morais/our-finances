"""Constrain export filenames to the caller's authorized local output directory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def output_path(
    output_dir: str | Path,
    filename: str | None,
    suffix: str,
    snapshot: dict[str, Any],
    filters: dict[str, Any] | None = None,
) -> Path:
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(
        json.dumps(filters or {}, sort_keys=True, default=str).encode()
    ).hexdigest()[:10]
    workspace = hashlib.sha256(str(snapshot["workspace_id"]).encode()).hexdigest()[:12]
    name = (
        filename
        or f"analytical-{workspace}-r{int(snapshot.get('revision', 0))}-{fingerprint}{suffix}"
    )
    if (
        Path(name).name != name
        or "/" in name
        or "\\" in name
        or ":" in name
        or not name.endswith(suffix)
    ):
        raise ValueError("Export filename must be a basename with the expected suffix")
    target = (directory / name).resolve()
    if target.parent != directory:
        raise ValueError("Export path escapes output directory")
    return target


def safe_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) or value.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + value
    return value
