"""Fictional isolated financial journey; provider networking is forbidden throughout."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import httpx
from aiogram import Bot
from aiogram.types import FSInputFile, Update
from cryptography.fernet import Fernet
from openpyxl import load_workbook
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import func, select

from app.agent.contracts import Interpretation, ProposedAction, QueryFilters, QueryRequest
from app.analytics import compute, pivot
from app.config import PROJECT_ROOT, Settings
from app.db import Database
from app.domain import FinanceService
from app.jobs.store import DurableStore
from app.models import AppliedCommand, AuditEvent, OutboxJob, PendingAction
from app.runtime import Runtime
from scripts.backup import create_backup
from scripts.restore import restore_backup

OWNER = 900900


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


@contextmanager
def forbidden_network() -> Iterator[dict[str, int]]:
    """Guard accidental provider calls, without replacing domain or artifact APIs."""
    attempts = {"count": 0}

    def deny(*_: Any, **__: Any) -> Any:
        attempts["count"] += 1
        raise RuntimeError("network_forbidden_in_local_validation")

    async def deny_async(*_: Any, **__: Any) -> Any:
        return deny()

    with (
        patch.object(socket.socket, "connect", deny),
        patch.object(socket.socket, "connect_ex", deny),
        patch.object(httpx.Client, "send", deny),
        patch.object(httpx.AsyncClient, "send", deny_async),
    ):
        yield attempts


class LocalBot:
    """Memory-only Telegram sink, with real recipient/artifact checks and no HTTP client."""

    id = OWNER + 1

    def __init__(self, report_directory: Path) -> None:
        self.report_directory = report_directory.resolve()
        self.message_count = 0
        self.delivered_files: list[Path] = []

    async def send_message(self, chat_id: int, text: str, **_: Any) -> None:
        check(chat_id == OWNER and bool(text), "Invalid local message destination/content")
        self.message_count += 1

    async def answer_callback_query(self, *_: Any, **__: Any) -> None:
        pass

    def record_file(self, chat_id: int, artifact: FSInputFile) -> None:
        path = Path(artifact.path).resolve()
        check(chat_id == OWNER, "Unexpected file recipient")
        check(path.is_relative_to(self.report_directory), "File escaped sandbox exports")
        check(path.is_file() and path.stat().st_size > 0, "Missing generated artifact")
        self.delivered_files.append(path)

    async def send_document(self, chat_id: int, document: FSInputFile, **_: Any) -> None:
        self.record_file(chat_id, document)

    async def send_photo(self, chat_id: int, photo: FSInputFile, **_: Any) -> None:
        self.record_file(chat_id, photo)


def action(operation: str, **payload: Any) -> ProposedAction:
    return ProposedAction.model_validate({"operation": operation, "payload": payload})


def callback_update(update_id: int, token: str) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"fictional-callback-{update_id}",
                "chat_instance": "local-fictional",
                "from": {"id": OWNER, "is_bot": False, "first_name": "Fixture"},
                "data": "confirm:" + token,
                "message": {
                    "message_id": update_id,
                    "date": 1793620800,
                    "chat": {"id": OWNER, "type": "private"},
                },
            },
        }
    )


async def confirm_actions(runtime: Runtime, actions: list[ProposedAction], update_id: int) -> None:
    revision = runtime.service.snapshot()["revision"]
    preview = await runtime.orchestrator.apply_interpretation(
        Interpretation(
            answer="Prévia fictícia",
            explanation="Jornada local isolada",
            needs_clarification=False,
            actions=actions,
        ),
        OWNER,
        OWNER,
    )
    check(runtime.service.snapshot()["revision"] == revision, "Proposal wrote before confirmation")
    token = preview.confirmation_token
    check(token is not None, "Missing durable confirmation")
    assert token is not None
    update = callback_update(update_id, token)
    check(runtime.ingest(update) and runtime.ingest(update), "Ingress rejected fixture")
    row = next(
        item
        for item in runtime.store.pending_inbounds(f"telegram:{LocalBot.id}")
        if item["external_id"] == str(update_id)
    )
    await runtime.process_inbound(row["id"])
    await runtime.process_inbound(row["id"])
    check(runtime.service.snapshot()["revision"] == revision + 1, "Confirmation did not apply once")
    runtime.orchestrator.confirm(token, OWNER, OWNER)
    check(
        runtime.service.snapshot()["revision"] == revision + 1, "Replay repeated a financial action"
    )


def totals(snapshot: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    result = compute(snapshot, filters)
    check(len(result["totals_by_currency"]) == 1, "Fixture must contain BRL only")
    row = result["totals_by_currency"][0]
    return {
        key: row[key]
        for key in (
            "currency",
            "income_minor",
            "expense_minor",
            "net_minor",
            "expense_transaction_count",
        )
    }


def artifact_metadata(path: Path, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


async def run_local_journey(
    data_directory: Path,
    report_directory: Path,
    *,
    evidence_path: Path,
) -> dict[str, Any]:
    """Use new fictional directories only; no default DB, .env, real keys or recipients."""
    data_directory, report_directory = data_directory.resolve(), report_directory.resolve()
    data_directory.mkdir(parents=True, exist_ok=False)
    report_directory.mkdir(parents=True, exist_ok=False)
    source_path, restored_path = (
        data_directory / "source.sqlite3",
        data_directory / "restored.sqlite3",
    )
    settings = Settings(
        _env_file=None,
        app_mode="offline",
        telegram_owner_user_id=OWNER,
        openai_api_key=None,
        elevenlabs_api_key=None,
        telegram_bot_token=None,
        database_url=SecretStr("sqlite+pysqlite:///" + source_path.as_posix()),
        report_directory=report_directory,
        app_timezone="America/Sao_Paulo",
        telegram_transport="disabled",
        run_worker_in_app=False,
    )
    with forbidden_network() as attempts:
        database = Database(settings.database_url.get_secret_value())
        bot = LocalBot(report_directory)
        runtime: Runtime | None = None
        restored_db: Database | None = None
        try:
            runtime = Runtime(settings, database=database, bot=cast(Bot, bot))
            today = date.fromisoformat(runtime.service.snapshot()["as_of"])
            day, start = today.isoformat(), today.replace(day=1)
            end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
            query_filters = QueryFilters(
                start_date=start.isoformat(), end_date=end.isoformat(), basis="cash"
            )
            filters = query_filters.to_analytics_filters()
            await confirm_actions(
                runtime,
                [
                    action("create_area", name="Estudo fictício"),
                    action("create_category", name="Curso fictício", type="expense", area_id="$0"),
                    action(
                        "create_category", name="Trabalho fictício", type="expense", area_id="$0"
                    ),
                    action(
                        "create_account",
                        name="Banco fictício",
                        type="bank",
                        currency="BRL",
                        opening_balance_minor=200000,
                        opening_date=day,
                    ),
                    action(
                        "create_account",
                        name="Reserva fictícia",
                        type="bank",
                        currency="BRL",
                        opening_balance_minor=0,
                        opening_date=day,
                    ),
                    action(
                        "create_budget",
                        name="Limite fictício",
                        amount_minor=100000,
                        currency="BRL",
                        period="month",
                        start_date=start.isoformat(),
                        end_date=end.isoformat(),
                        basis="cash",
                        category_id="$1",
                    ),
                ],
                1,
            )
            snapshot = runtime.service.snapshot()
            course, work = [
                r["id"] for r in sorted(snapshot["categories"], key=lambda r: r["name"])
            ]
            bank, reserve = [r["id"] for r in sorted(snapshot["accounts"], key=lambda r: r["name"])]
            await confirm_actions(
                runtime,
                [
                    action(
                        "create_transaction",
                        type="expense",
                        amount_minor=12345,
                        currency="BRL",
                        occurrence_date=day,
                        account_id=bank,
                        description="Compra fictícia corrigível",
                        allocations=[{"amount_minor": 12345, "category_id": course}],
                    )
                ],
                2,
            )
            purchase_id = runtime.service.snapshot()["transactions"][0]["id"]
            await confirm_actions(
                runtime,
                [
                    action(
                        "create_transaction",
                        type="expense",
                        amount_minor=60000,
                        currency="BRL",
                        occurrence_date=day,
                        account_id=bank,
                        description="Curso com rateio fictício",
                        allocations=[
                            {"amount_minor": 30000, "category_id": course},
                            {"amount_minor": 30000, "category_id": work},
                        ],
                    )
                ],
                3,
            )
            await confirm_actions(
                runtime, [action("update_transaction", id=purchase_id, amount_minor=15000)], 4
            )
            await confirm_actions(
                runtime,
                [
                    action(
                        "refund_transaction",
                        id=purchase_id,
                        amount_minor=5000,
                        occurrence_date=day,
                    )
                ],
                5,
            )
            await confirm_actions(
                runtime,
                [
                    action(
                        "create_transaction",
                        type="transfer",
                        amount_minor=25000,
                        currency="BRL",
                        occurrence_date=day,
                        account_id=bank,
                        to_account_id=reserve,
                    )
                ],
                6,
            )
            await confirm_actions(
                runtime,
                [
                    action(
                        "create_report",
                        name="Análise fictícia",
                        rows=["category"],
                        columns=["month"],
                        metrics=["expense_minor", "transaction_count"],
                        chart="column",
                        filters=query_filters.model_dump(),
                    )
                ],
                7,
            )
            snapshot = runtime.service.snapshot()
            expected = {
                "currency": "BRL",
                "income_minor": 0,
                "expense_minor": 70000,
                "net_minor": -70000,
                "expense_transaction_count": 2,
            }
            observed = totals(snapshot, filters)
            check(observed == expected, "Ledger differs from independent fixture arithmetic")
            check(len(snapshot["transactions"]) == 4, "Replay/split duplicated a transaction")
            check(
                sum(r["amount_minor"] for r in snapshot["allocations"]) == 80000,
                "Corrected expense, split and refund allocations do not reconcile",
            )
            analytics = compute(snapshot, filters)
            balances = {r["account_id"]: r["balance_minor"] for r in analytics["balances"]}
            check(balances == {bank: 105000, reserve: 25000}, "Account balances differ")
            check(analytics["budgets"][0]["actual_minor"] == 40000, "Budget split/refund mismatch")
            summary = await runtime.orchestrator.answer_query(
                QueryRequest(kind="summary", filters=query_filters)
            )
            saved_pivot = await runtime.orchestrator.answer_query(
                QueryRequest(
                    kind="report",
                    report_id=snapshot["reports"][0]["id"],
                )
            )
            matrix = pivot(
                snapshot,
                {
                    "rows": ["category"],
                    "columns": ["month"],
                    "metrics": ["expense_minor"],
                    "filters": {**filters, "types": ["expense", "refund"]},
                },
            )
            check(
                {r["category"]: r["expense_minor"] for r in matrix["cells"]}
                == {
                    "Curso fictício": 40000,
                    "Trabalho fictício": 30000,
                },
                "Pivot duplicated allocation/transfer/refund amounts",
            )
            check(
                "40000" in saved_pivot.text and "30000" in saved_pivot.text,
                "Saved analysis lost its definition",
            )
            summary_path, pivot_path = (
                report_directory / "summary.txt",
                report_directory / "pivot.json",
            )
            summary_path.write_text(summary.text, encoding="utf-8")
            pivot_path.write_text(
                json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            artifacts = [(summary_path, "summary"), (pivot_path, "pivot")]
            for kind, output in [("export", "csv"), ("export", "xlsx"), ("chart", "png")]:
                query = QueryRequest.model_validate(
                    {
                        "kind": kind,
                        "format": output,
                        "filters": query_filters.model_dump(),
                    }
                )
                reply = await runtime.orchestrator.answer_query(query)
                check(len(reply.files) == 1, "Missing generated export")
                artifacts.append((reply.files[0], output))
                runtime.enqueue_reply(reply, "smoke:" + output)
            paths = {kind: path for path, kind in artifacts}
            with paths["csv"].open(encoding="utf-8-sig", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            check(sum(int(r["expense_minor"]) for r in csv_rows) == 70000, "CSV totals differ")
            workbook: Any = load_workbook(paths["xlsx"], data_only=False)
            native_charts, tables = 0, 0
            for worksheet in workbook.worksheets:
                native_charts += len(worksheet._charts)
                tables += len(worksheet.tables)
            check(native_charts > 0 and tables > 0, "XLSX lacks real charts/tables")
            fact_rows: list[tuple[Any, ...]] = list(workbook["Rateios"].values)
            expense_column = list(fact_rows[0]).index("expense_minor")
            check(sum(int(r[expense_column]) for r in fact_rows[1:]) == 70000, "XLSX facts differ")
            workbook.close()
            with Image.open(paths["png"]) as picture:
                check(
                    picture.format == "PNG" and picture.width > 0 and picture.height > 0,
                    "Chart is not a valid PNG",
                )
            for _ in range(100):
                if not await runtime.run_one_job():
                    break
            else:
                raise AssertionError("Queue did not settle within bounded work")
            check(
                set(bot.delivered_files) == {paths["csv"], paths["xlsx"], paths["png"]},
                "Generated files did not pass through the local Telegram sink",
            )
            with database.session() as session:
                audit_count = session.scalar(select(func.count()).select_from(AuditEvent))
                command_count = session.scalar(select(func.count()).select_from(AppliedCommand))
            check(audit_count == command_count == 7, "Replay changed audit/idempotency counts")
            key = Fernet.generate_key()
            with (data_directory / "fixture-backup.key").open("xb") as handle:
                handle.write(key)
            backup_path = create_backup(database, data_directory / "fixture.ofbackup", key)
            restored_db = Database("sqlite+pysqlite:///" + restored_path.as_posix())
            restore_counts = restore_backup(backup_path, restored_db, key)
            restored = FinanceService(restored_db, OWNER).snapshot()
            restored_totals = totals(restored, filters)
            check(restored_totals == expected, "Restored totals differ")
            check(
                restored["transactions"] == snapshot["transactions"],
                "Restore changed transaction IDs",
            )
            check(
                DurableStore(restored_db).claim("forbidden-restored-worker") is None,
                "Restored jobs may execute external effects",
            )
            with restored_db.session() as session:
                pending_states = set(session.scalars(select(PendingAction.status)).all())
                job_states = set(session.scalars(select(OutboxJob.status)).all())
            check(
                pending_states == {"cancelled"} and job_states == {"uncertain"},
                "Restore did not suspend callbacks/external jobs",
            )
            check(attempts["count"] == 0, "A provider network request was attempted")
            artifacts += [
                (backup_path, "encrypted_backup"),
                (source_path, "source_database"),
                (restored_path, "restored_database"),
            ]
            result: dict[str, Any] = {
                "ok": True,
                "fictional": True,
                "owner_fixture_id": OWNER,
                "date": day,
                "provider_calls": 0,
                "network_attempts": attempts["count"],
                "telegram_network_calls": 0,
                "fake_telegram_messages": bot.message_count,
                "revision": snapshot["revision"],
                "transaction_count": 4,
                "audit_count": audit_count,
                "idempotent_command_count": command_count,
                "expected_totals": expected,
                "observed_totals": observed,
                "restored_totals": restored_totals,
                "restore_row_counts": restore_counts,
                "xlsx_native_chart_count": native_charts,
                "xlsx_table_count": tables,
                "online_native_pivot_verified": False,
                "artifacts": [artifact_metadata(path, kind) for path, kind in artifacts],
            }
        finally:
            if restored_db is not None:
                restored_db.close()
            if runtime is not None:
                runtime.close()
            else:
                database.close()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    check(not evidence_path.is_symlink(), "Evidence destination cannot be a symlink")
    evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    session = str(uuid4())
    evidence = PROJECT_ROOT / "data" / "sandbox" / "local-validation.json"
    try:
        result = asyncio.run(
            run_local_journey(
                PROJECT_ROOT / "data" / "sandbox" / session,
                PROJECT_ROOT / "exports" / "sandbox" / session,
                evidence_path=evidence,
            )
        )
        print(
            json.dumps(
                {
                    "ok": result["ok"],
                    "fictional": True,
                    "provider_calls": 0,
                    "evidence": str(evidence),
                    "artifacts": [item["path"] for item in result["artifacts"]],
                },
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "fictional": True, "reason": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
