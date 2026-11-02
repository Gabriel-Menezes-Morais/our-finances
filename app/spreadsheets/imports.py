"""Validate and preview spreadsheet changes; application remains a domain command.

This module never executes formulas and never writes financial records directly.
The domain must recheck base_revision in the same transaction as its confirmed edit.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any, Literal
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.query import validate_snapshot
from app.spreadsheets.conflicts import check_revision

ALLOWED_FIELDS = {
    "transaction": {
        "description",
        "amount_minor",
        "currency",
        "occurrence_date",
        "competence_date",
        "settlement_date",
        "type",
        "account_id",
        "to_account_id",
        "status",
        "tags",
        "allocations",
        "refund_of",
    },
    "category": {"name", "parent_id", "area_id", "aliases", "type", "variability", "necessity"},
    "budget": {
        "name",
        "amount_minor",
        "currency",
        "period",
        "start_date",
        "end_date",
        "category_id",
        "area_id",
        "project_id",
        "responsible_id",
        "thresholds",
        "carryover",
        "basis",
    },
}
COLLECTIONS = {"transaction": "transactions", "category": "categories", "budget": "budgets"}


class StagedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    workspace_id: str
    entity: Literal["transaction", "category", "budget"]
    operation: Literal["create", "update"]
    entity_id: str | None = None
    base_revision: int = Field(ge=0, strict=True)
    values: dict[str, Any]

    @model_validator(mode="after")
    def allowed_fields(self) -> StagedChange:
        if not self.values or set(self.values) - ALLOWED_FIELDS[self.entity]:
            raise ValueError("Unexpected or empty change fields")
        if self.operation == "update" and not self.entity_id:
            raise ValueError("Updates require an entity_id")
        if self.operation == "create" and self.entity_id:
            raise ValueError("Create IDs are assigned by the domain")
        return self


def preview_changes(
    snapshot: dict[str, Any],
    changes: list[dict[str, Any]],
    *,
    processed_ids: set[str] | None = None,
) -> dict[str, Any]:
    validate_snapshot(snapshot)
    if len(changes) > 5000:
        raise ValueError("At most 5000 staged rows per preview")
    seen = set(processed_ids or ())
    accepted: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    duplicates: list[str] = []
    invalid: list[dict[str, Any]] = []
    entities = {
        kind: {r["id"]: r for r in snapshot.get(table, [])} for kind, table in COLLECTIONS.items()
    }
    for raw in changes:
        try:
            change = StagedChange.model_validate(raw)
            if change.workspace_id != snapshot["workspace_id"]:
                raise ValueError("Change belongs to another workspace")
            if change.id in seen:
                duplicates.append(change.id)
                continue
            seen.add(change.id)
            current = entities[change.entity].get(change.entity_id) if change.entity_id else None
            if change.operation == "update" and current is None:
                raise ValueError("Entity no longer exists")
            revision = (
                current.get("revision", 0) if current is not None else snapshot.get("revision", 0)
            )
            if change.base_revision != revision:
                conflicts.append(
                    {
                        "id": change.id,
                        "entity_id": change.entity_id,
                        "base_revision": change.base_revision,
                        "current_revision": revision,
                        "status": "conflict",
                    }
                )
                continue
            accepted.append(
                {
                    "change": change.model_dump(mode="json"),
                    "before": current,
                    "after": {**(current or {}), **change.values},
                    "status": "requires_domain_validation_and_confirmation",
                }
            )
        except ValueError:
            # Do not echo arbitrary cell content or validation errors containing data.
            invalid.append(
                {
                    "row": len(accepted) + len(conflicts) + len(duplicates) + len(invalid) + 1,
                    "status": "invalid_fields_or_workspace",
                }
            )
    digest = hashlib.sha256(
        json.dumps(accepted, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    return {
        "workspace_id": snapshot["workspace_id"],
        "snapshot_revision": snapshot.get("revision", 0),
        "preview_hash": digest,
        "accepted": accepted,
        "conflicts": conflicts,
        "duplicates": duplicates,
        "invalid": invalid,
        "applied": False,
        "requires_confirmation": True,
    }


def confirmed_commands(
    snapshot: dict[str, Any], preview: dict[str, Any], confirmed_hash: str
) -> list[dict[str, Any]]:
    """Build domain commands only after an exact preview confirmation and recheck."""
    validate_snapshot(snapshot)
    if (
        snapshot["workspace_id"] != preview.get("workspace_id")
        or preview.get("preview_hash") != confirmed_hash
    ):
        raise ValueError("Confirmation does not match this workspace and preview")
    check_revision(preview["snapshot_revision"], snapshot.get("revision", 0))
    expected = hashlib.sha256(
        json.dumps(preview["accepted"], sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    if expected != confirmed_hash:
        raise ValueError("Preview content changed")
    if preview["conflicts"] or preview["invalid"]:
        raise ValueError("Resolve invalid rows and revision conflicts before confirming")
    return [
        {**row["change"], "idempotency_key": f"sheet-change:{row['change']['id']}"}
        for row in preview["accepted"]
    ]


def _cell_formula(value: Any) -> bool:
    return isinstance(value, str) and value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "@"))


def _parse_rows(
    rows: list[list[Any]], snapshot: dict[str, Any], fingerprint: str
) -> list[dict[str, Any]]:
    validate_snapshot(snapshot)
    if not rows:
        return []
    headers = [str(value or "").strip() for value in rows[0]]
    if len(headers) != len(set(headers)) or not all(headers):
        raise ValueError("Import headers must be nonempty and unique")
    changes: list[dict[str, Any]] = []
    for row_index, values in enumerate(rows[1:], 2):
        if not any(value is not None and str(value).strip() for value in values):
            continue
        if len(changes) >= 5000:
            raise ValueError("Import exceeds 5000 rows")
        if len(values) > len(headers) and any(
            value is not None for value in values[len(headers) :]
        ):
            raise ValueError("Import row has unexpected cells")
        row = dict(zip(headers, values, strict=False))
        if any(_cell_formula(value) for value in values):
            raise ValueError("Spreadsheet formulas are not allowed in staged input")
        if "values_json" in row:
            if not row.get("values_json"):
                # The exported blank manual-entry template is not an edit.
                continue
            if set(headers) - {
                "id",
                "workspace_id",
                "entity",
                "operation",
                "entity_id",
                "base_revision",
                "values_json",
                "status",
            }:
                raise ValueError("Unexpected staging headers")
            try:
                payload = json.loads(str(row["values_json"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("values_json must contain a JSON object") from exc
            if not isinstance(payload, dict):
                raise ValueError("values_json must contain a JSON object")
            change = {
                "id": str(row.get("id") or f"{fingerprint}:{row_index}"),
                "workspace_id": str(row.get("workspace_id") or snapshot["workspace_id"]),
                "entity": row.get("entity"),
                "operation": row.get("operation"),
                "entity_id": row.get("entity_id") or None,
                "base_revision": _integer(row.get("base_revision"), "base_revision"),
                "values": payload,
            }
        else:
            allowed = ALLOWED_FIELDS["transaction"] | {
                "id",
                "base_revision",
                "entity_id",
                "operation",
                "workspace_id",
                "values_json",
            }
            if set(headers) - allowed or not {
                "amount_minor",
                "occurrence_date",
                "type",
                "account_id",
            }.issubset(headers):
                raise ValueError(
                    "Use staging headers or explicit transaction headers with "
                    "amount_minor, occurrence_date, type and account_id"
                )
            payload = {
                key: value
                for key, value in row.items()
                if key in ALLOWED_FIELDS["transaction"] and value is not None and value != ""
            }
            payload["amount_minor"] = _integer(payload["amount_minor"], "amount_minor")
            for key in ("tags", "allocations"):
                if key in payload and isinstance(payload[key], str):
                    try:
                        payload[key] = json.loads(payload[key])
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{key} must be a JSON array") from exc
            change = {
                "id": str(row.get("id") or f"{fingerprint}:{row_index}"),
                "workspace_id": str(row.get("workspace_id") or snapshot["workspace_id"]),
                "entity": "transaction",
                "operation": row.get("operation") or "create",
                "entity_id": row.get("entity_id") or None,
                "base_revision": _integer(
                    row.get("base_revision", snapshot.get("revision", 0)), "base_revision"
                ),
                "values": payload,
            }
        validated = StagedChange.model_validate(change)
        if validated.workspace_id != snapshot["workspace_id"]:
            raise ValueError("Import row belongs to another workspace")
        changes.append(validated.model_dump(mode="json"))
    return changes


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"{field} must be integer")


def parse_csv(data: bytes, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Import exceeds 20 MB")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must use UTF-8 encoding") from exc
    try:
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(content, newline=""), dialect=dialect)
    rows: list[list[Any]] = []
    for row in reader:
        if len(rows) > 5000:
            raise ValueError("Import exceeds 5000 rows")
        rows.append(row)
    return _parse_rows(rows, snapshot, hashlib.sha256(data).hexdigest())


def parse_xlsx(data: bytes, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Import exceeds 20 MB")
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError("Expanded workbook exceeds 100 MB")
            if any(
                "vbaproject" in name.lower() or "externallinks/" in name.lower()
                for name in archive.namelist()
            ):
                raise ValueError("Macros and external workbook links are not allowed")
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except BadZipFile as exc:
        raise ValueError("Invalid XLSX file") from exc
    try:
        if "Entrada_Alteracoes" not in wb.sheetnames:
            raise ValueError("Workbook must include Entrada_Alteracoes")
        ws = wb["Entrada_Alteracoes"]
        if ws.max_column > 32 or ws.max_row > 5001:
            raise ValueError("Staging sheet exceeds 5000 rows or 32 columns")
        rows = []
        for row in ws.iter_rows():
            if any(cell.data_type == "f" for cell in row):
                raise ValueError("Formulas are not allowed in Entrada_Alteracoes")
            rows.append([cell.value for cell in row])
        return _parse_rows(rows, snapshot, hashlib.sha256(data).hexdigest())
    finally:
        wb.close()
