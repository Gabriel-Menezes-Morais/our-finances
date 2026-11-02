"""The same offline smoke journey executes against fresh real SQLite and artifact files."""

import asyncio
import json
from pathlib import Path

from scripts.smoke_local import run_local_journey


def test_fictional_local_journey_has_exact_finances_exports_and_restoration(tmp_path: Path) -> None:
    evidence_path = tmp_path / "local-validation.json"
    result = asyncio.run(
        run_local_journey(
            tmp_path / "isolated-data",
            tmp_path / "isolated-exports",
            evidence_path=evidence_path,
        )
    )
    assert result["ok"] is True and result["fictional"] is True
    assert (
        result["provider_calls"]
        == result["network_attempts"]
        == result["telegram_network_calls"]
        == 0
    )
    assert (
        result["observed_totals"]
        == result["restored_totals"]
        == {
            "currency": "BRL",
            "income_minor": 0,
            "expense_minor": 70000,
            "net_minor": -70000,
            "expense_transaction_count": 2,
        }
    )
    assert result["transaction_count"] == 4
    assert result["audit_count"] == result["idempotent_command_count"] == 7
    assert result["xlsx_native_chart_count"] > 0 and result["xlsx_table_count"] > 0
    assert result["online_native_pivot_verified"] is False
    assert {item["kind"] for item in result["artifacts"]} >= {
        "csv",
        "xlsx",
        "png",
        "encrypted_backup",
        "source_database",
        "restored_database",
    }
    for artifact in result["artifacts"]:
        assert Path(artifact["path"]).is_relative_to(tmp_path)
        assert artifact["bytes"] > 0 and len(artifact["sha256"]) == 64
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == result
