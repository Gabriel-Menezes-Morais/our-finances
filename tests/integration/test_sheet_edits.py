import io
import json

import pytest
from openpyxl import Workbook

from app.spreadsheets.conflicts import RevisionConflict
from app.spreadsheets.imports import (
    confirmed_commands,
    parse_csv,
    parse_xlsx,
    preview_changes,
)


def source():
    return {
        "workspace_id": "w",
        "revision": 5,
        "transactions": [{"id": "tx", "revision": 2, "amount_minor": 60000}],
    }


def change(**overrides):
    return {
        "id": "edit-1",
        "workspace_id": "w",
        "entity": "transaction",
        "operation": "update",
        "entity_id": "tx",
        "base_revision": 2,
        "values": {"description": "=untrusted text", "amount_minor": 10000},
        **overrides,
    }


def test_staged_change_requires_exact_confirmation_and_current_revision():
    snapshot = source()
    preview = preview_changes(snapshot, [change()])
    assert preview["applied"] is False
    assert snapshot["transactions"][0]["amount_minor"] == 60000
    commands = confirmed_commands(snapshot, preview, preview["preview_hash"])
    assert commands[0]["values"]["description"] == "=untrusted text"
    assert commands[0]["idempotency_key"] == "sheet-change:edit-1"
    with pytest.raises(ValueError):
        confirmed_commands(snapshot, preview, "wrong-hash")
    with pytest.raises(RevisionConflict):
        confirmed_commands({**snapshot, "revision": 6}, preview, preview["preview_hash"])


def test_conflicts_duplicates_and_unknown_fields_are_explicit():
    preview = preview_changes(
        source(),
        [
            change(base_revision=1),
            change(id="other", workspace_id="other"),
            change(id="bad", values={"execute_sql": "drop"}),
        ],
    )
    assert len(preview["conflicts"]) == 1
    assert len(preview["invalid"]) == 2
    with pytest.raises(ValueError):
        confirmed_commands(source(), preview, preview["preview_hash"])
    twice = preview_changes(source(), [change(), change()])
    assert len(twice["accepted"]) == 1
    assert twice["duplicates"] == ["edit-1"]
    assert preview_changes(source(), [change()], processed_ids={"edit-1"})["accepted"] == []


def test_preview_tamper_is_rejected():
    preview = preview_changes(source(), [change()])
    digest = preview["preview_hash"]
    preview["accepted"][0]["change"]["values"]["amount_minor"] = 999999
    with pytest.raises(ValueError, match="content changed"):
        confirmed_commands(source(), preview, digest)


def test_csv_explicit_minor_units_and_stable_import_ids():
    data = (
        b"type,amount_minor,occurrence_date,account_id,description\n"
        b"expense,1234,2026-11-01,bank,Almoco\n"
    )
    changes = parse_csv(data, source())
    assert changes[0]["values"]["amount_minor"] == 1234
    assert changes[0]["base_revision"] == 5
    assert parse_csv(data, source())[0]["id"] == changes[0]["id"]
    with pytest.raises(ValueError):
        parse_csv(data.replace(b"1234", b"12.34"), source())
    with pytest.raises(ValueError, match="formulas"):
        parse_csv(data.replace(b"Almoco", b"=WEBSERVICE()"), source())


def manual_book(values_json, formula=False):
    wb = Workbook()
    ws = wb.active
    ws.title = "Entrada_Alteracoes"
    ws.append(
        [
            "id",
            "workspace_id",
            "entity",
            "operation",
            "entity_id",
            "base_revision",
            "values_json",
            "status",
        ]
    )
    ws.append(["edit-1", "w", "transaction", "update", "tx", 2, values_json, "pending"])
    # Generated sheets can have trusted formulas; only the allowlisted input is read.
    wb.create_sheet("Generated")["A1"] = "=SUM(1,2)"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_xlsx_only_manual_sheet_and_formula_rejection():
    changes = parse_xlsx(manual_book(json.dumps({"amount_minor": 4000})), source())
    assert changes[0]["values"]["amount_minor"] == 4000
    with pytest.raises(ValueError, match="Formulas"):
        parse_xlsx(manual_book("=1+1"), source())


def test_xlsx_expansion_and_invalid_data_guard():
    with pytest.raises(ValueError):
        parse_xlsx(b"this is not XLSX", source())
    with pytest.raises(ValueError):
        parse_csv(b"x" * (20 * 1024 * 1024 + 1), source())
