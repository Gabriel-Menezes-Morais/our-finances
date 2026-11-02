"""Authorized, deterministic financial commands. No model-generated SQL is accepted."""

import calendar
import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import Database
from app.models import (
    Allocation,
    AppliedCommand,
    AuditEvent,
    OutboxJob,
    Record,
    Transaction,
    Workspace,
    utcnow,
)

KINDS = {
    "area": "areas",
    "category": "categories",
    "project": "projects",
    "tag": "tags",
    "account": "accounts",
    "budget": "budgets",
    "goal": "goals",
    "contribution": "contributions",
    "recurrence": "recurrences",
    "installment": "installments",
    "report": "reports",
    "scenario": "scenarios",
    "schedule": "schedules",
    "asset": "assets",
    "liability": "liabilities",
}
FIELDS: dict[str, set[str]] = {
    "area": {"name", "aliases"},
    "category": {"name", "type", "parent_id", "area_id", "aliases", "variability", "necessity"},
    "project": {"name", "description", "deadline"},
    "tag": {"name"},
    "account": {
        "name",
        "type",
        "currency",
        "opening_balance_minor",
        "opening_date",
        "closing_day",
        "due_day",
    },
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
    "goal": {"name", "target_minor", "currency", "deadline", "project_id"},
    "contribution": {"goal_id", "amount_minor", "occurrence_date", "account_id", "description"},
    "recurrence": {
        "name",
        "frequency",
        "interval",
        "next_date",
        "end_date",
        "timezone",
        "exceptions",
        "template",
        "paused",
    },
    "schedule": {
        "name",
        "kind",
        "frequency",
        "interval",
        "next_run",
        "timezone",
        "destination",
        "paused",
    },
    "asset": {"name", "value_minor", "currency", "as_of", "description", "rate", "rate_period"},
    "liability": {
        "name",
        "value_minor",
        "currency",
        "as_of",
        "description",
        "rate",
        "rate_period",
        "payment_minor",
        "months",
    },
    "report": {
        "name",
        "rows",
        "columns",
        "metrics",
        "filters",
        "chart",
        "destination",
        "period",
        "order_by",
        "limit",
    },
    "scenario": {"name", "assumptions", "start_date", "end_date"},
}
TX_FIELDS = {
    "type",
    "amount_minor",
    "currency",
    "occurrence_date",
    "competence_date",
    "settlement_date",
    "status",
    "description",
    "account_id",
    "to_account_id",
    "refund_of",
    "allocations",
    "tags",
    "installment_count",
    "first_due_date",
    "variability",
    "necessity",
    "responsible_id",
    "fx_rate",
    "fx_date",
    "fx_source",
}


class DomainError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise DomainError(code, message)


def integer(value: Any, field: str, *, minimum: int | None = 0) -> int:
    require(type(value) is int, "invalid_amount", f"{field} deve ser inteiro em unidades mínimas.")
    require(minimum is None or value >= minimum, "invalid_amount", f"{field} fora do intervalo.")
    require(abs(value) <= 9_000_000_000_000_000, "invalid_amount", f"{field} muito grande.")
    return int(value)


def iso_date(value: Any, field: str) -> str:
    try:
        require(isinstance(value, str), "invalid_date", f"Informe {field} no formato AAAA-MM-DD.")
        parsed = date.fromisoformat(value)
        require(parsed.isoformat() == value, "invalid_date", f"Formato inválido em {field}.")
        return parsed.isoformat()
    except (ValueError, TypeError) as exc:
        raise DomainError("invalid_date", f"Data inválida em {field}.") from exc


def decimal_string(value: Any, *, positive: bool = False) -> str:
    try:
        require(
            not isinstance(value, (float, bool)), "invalid_rate", "Taxa deve ser decimal exata."
        )
        number = Decimal(str(value))
        require(
            number.is_finite() and number >= 0 and (not positive or number > 0),
            "invalid_rate",
            "Taxa inválida.",
        )
        return str(number)
    except InvalidOperation as exc:
        raise DomainError("invalid_rate", "Taxa inválida.") from exc


def add_months(value: date, count: int, anchor_day: int | None = None) -> date:
    month = value.month - 1 + count
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(anchor_day or value.day, calendar.monthrange(year, month)[1]))


def currency_digits(currency: str) -> int:
    """Minor-unit arithmetic, including zero/three/four-decimal currencies."""
    if currency in {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "PYG",
        "RWF",
        "UGX",
        "UYI",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }:
        return 0
    if currency in {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}:
        return 3
    if currency in {"CLF", "UYW"}:
        return 4
    require(
        currency
        in {
            "BRL",
            "USD",
            "EUR",
            "GBP",
            "CHF",
            "CAD",
            "AUD",
            "NZD",
            "CNY",
            "HKD",
            "SGD",
            "TWD",
            "ARS",
            "UYU",
            "COP",
            "PEN",
            "BOB",
            "MXN",
            "ZAR",
            "INR",
            "AED",
            "SAR",
            "ILS",
            "TRY",
            "RUB",
            "PLN",
            "CZK",
            "HUF",
            "RON",
            "SEK",
            "NOK",
            "DKK",
            "THB",
            "MYR",
            "PHP",
            "IDR",
            "PKR",
            "BDT",
            "EGP",
            "NGN",
            "KES",
            "MAD",
            "QAR",
            "DOP",
            "CRC",
        },
        "unsupported_currency",
        "Precisão desta moeda ainda não está configurada.",
    )
    return 2


class FinanceService:
    def __init__(self, database: Database, owner_id: int, workspace_id: str | None = None) -> None:
        require(type(owner_id) is int and owner_id > 0, "forbidden", "Identidade não autorizada.")
        self.database = database
        self.owner_id = owner_id
        self.workspace_id = workspace_id

    def _workspace(self, session: Session) -> Workspace:
        if self.database.engine.dialect.name == "postgresql":
            from sqlalchemy import text

            # Lock also covers first workspace creation, before any row exists.
            session.execute(text("SELECT pg_advisory_xact_lock(:owner)"), {"owner": self.owner_id})
        if self.workspace_id:
            workspace = session.scalar(
                select(Workspace).where(Workspace.id == self.workspace_id).with_for_update()
            )
            require(
                workspace is not None and workspace.owner_id == self.owner_id,
                "forbidden",
                "Sem permissão para este espaço financeiro.",
            )
            assert workspace is not None
            return workspace
        workspace = session.scalar(
            select(Workspace).where(Workspace.owner_id == self.owner_id).with_for_update()
        )
        if workspace is None:
            # owner_id comes from the already authenticated application session.
            workspace = Workspace(owner_id=self.owner_id)
            session.add(workspace)
            session.flush()
        return workspace

    def snapshot(self) -> dict[str, Any]:
        with self.database.session() as session:
            result = self._snapshot(session, self._workspace(session))
        self.workspace_id = result["workspace_id"]
        return result

    def _snapshot(self, session: Session, workspace: Workspace) -> dict[str, Any]:
        session.flush()
        result: dict[str, Any] = {
            "workspace_id": workspace.id,
            "revision": workspace.revision,
            "currency": workspace.currency,
            "timezone": workspace.timezone,
            "name": workspace.name,
            "operations": deepcopy(workspace.flags),
            "generated_at": utcnow(),
            "as_of": datetime.now(ZoneInfo(workspace.timezone)).date().isoformat(),
        }
        result.update({plural: [] for plural in KINDS.values()})
        for record in session.scalars(
            select(Record)
            .where(Record.workspace_id == workspace.id)
            .order_by(Record.created_at, Record.id)
        ):
            result[KINDS[record.kind]].append(
                {**deepcopy(record.data), "id": record.id, "revision": record.revision}
            )
        result["transactions"] = [
            self._transaction_dict(row)
            for row in session.scalars(
                select(Transaction)
                .where(Transaction.workspace_id == workspace.id)
                .order_by(Transaction.created_at, Transaction.id)
            )
        ]
        result["transactions"].sort(
            key=lambda item: (
                item.get("created_sequence", item.get("created_revision", item["revision"])),
                item["id"],
            )
        )
        result["allocations"] = [
            {
                **deepcopy(row.data),
                "id": row.id,
                "transaction_id": row.transaction_id,
                "amount_minor": row.amount_minor,
            }
            for row in session.scalars(
                select(Allocation)
                .where(Allocation.workspace_id == workspace.id)
                .order_by(Allocation.id)
            )
        ]
        transaction_order = {row["id"]: index for index, row in enumerate(result["transactions"])}
        result["installments"].sort(
            key=lambda row: (transaction_order.get(row["transaction_id"], 0), row["number"])
        )
        return result

    @staticmethod
    def _transaction_dict(row: Transaction) -> dict[str, Any]:
        return {
            **deepcopy(row.data),
            "id": row.id,
            "type": row.type,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
            "occurrence_date": row.occurrence_date,
            "status": row.status,
            "revision": row.revision,
        }

    def context(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        snapshot["operation_fields"] = {
            **{
                f"{verb}_{kind}": sorted(fields | ({"id"} if verb != "create" else set()))
                for kind, fields in FIELDS.items()
                for verb in ("create", "update", "archive")
            },
            "create_transaction": sorted(TX_FIELDS),
            "update_transaction": sorted(TX_FIELDS | {"id"}),
            "cancel_transaction": ["id"],
            "refund_transaction": ["id", "amount_minor", "occurrence_date"],
            "merge_category": ["id", "target_id"],
            "merge_area": ["id", "target_id"],
            "settle_card": ["account_id", "to_account_id", "amount_minor", "occurrence_date"],
            "generate_recurrences": ["through_date"],
            "set_operations": ["flags"],
            "undo": [],
            "configure_workspace": ["name", "currency", "timezone"],
            "duplicate_report": ["id", "name"],
            "duplicate_scenario": ["id", "name"],
        }
        return snapshot

    def execute(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        result = self.execute_batch(
            [{"operation": operation, "payload": payload}],
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
        return {**result["results"][0], "revision": result["revision"]}

    def execute_batch(
        self,
        actions: list[dict[str, Any]],
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        require(
            isinstance(idempotency_key, str) and 0 < len(idempotency_key) <= 300,
            "invalid_key",
            "Chave de origem inválida.",
        )
        require(
            isinstance(actions, list) and 0 < len(actions) <= 100,
            "invalid_batch",
            "Informe entre uma e cem ações.",
        )
        try:
            fingerprint = hashlib.sha256(
                json.dumps(actions, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
        except (ValueError, TypeError) as exc:
            raise DomainError("invalid_payload", "Ação contém dados inválidos.") from exc
        with self.database.session() as session:
            workspace = self._workspace(session)
            previous = session.scalar(
                select(AppliedCommand).where(
                    AppliedCommand.workspace_id == workspace.id,
                    AppliedCommand.key == idempotency_key,
                )
            )
            if previous:
                require(
                    previous.fingerprint == fingerprint,
                    "idempotency_conflict",
                    "Esta origem já foi aplicada com conteúdo diferente.",
                )
                self.workspace_id = workspace.id
                return deepcopy(previous.result)
            require(
                expected_revision is None or workspace.revision == expected_revision,
                "revision_conflict",
                "Os dados mudaram. Revise a prévia antes de confirmar.",
            )
            before = self._snapshot(session, workspace)
            workspace.revision += 1
            results: list[dict[str, Any]] = []
            for action in actions:
                require(
                    isinstance(action, dict) and set(action) == {"operation", "payload"},
                    "invalid_payload",
                    "Ação inválida.",
                )
                results.append(
                    self._dispatch(
                        session,
                        workspace,
                        action["operation"],
                        self._resolve_batch_references(deepcopy(action["payload"]), results),
                    )
                )
                results[-1]["operation"] = action["operation"]
                identifier = results[-1].get("id")
                transaction = session.get(Transaction, identifier) if identifier else None
                if transaction is not None and transaction.workspace_id == workspace.id:
                    transaction.data = {
                        **transaction.data,
                        "source_key": transaction.data.get("source_key", idempotency_key),
                    }
                    if "transaction" in results[-1]:
                        results[-1]["transaction"] = self._transaction_dict(transaction)
            after = self._snapshot(session, workspace)
            session.add(
                AuditEvent(
                    workspace_id=workspace.id,
                    owner_id=self.owner_id,
                    revision=workspace.revision,
                    operation=";".join(a["operation"] for a in actions),
                    before=before,
                    after=after,
                )
            )
            session.add(
                OutboxJob(
                    workspace_id=workspace.id,
                    kind="publish_snapshot",
                    payload={"workspace_id": workspace.id, "revision": workspace.revision},
                    dedupe_key=f"snapshot:{workspace.id}:{workspace.revision}",
                )
            )
            result: dict[str, Any] = {
                "workspace_id": workspace.id,
                "revision": workspace.revision,
                "results": results,
            }
            session.add(
                AppliedCommand(
                    workspace_id=workspace.id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    result=result,
                )
            )
        self.workspace_id = result["workspace_id"]
        return result

    @staticmethod
    def _resolve_batch_references(
        value: Any, previous: list[dict[str, Any]], field: str = ""
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: FinanceService._resolve_batch_references(item, previous, key)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                FinanceService._resolve_batch_references(item, previous, field) for item in value
            ]
        if isinstance(value, str) and re.fullmatch(r"\$\d+", value):
            index = int(value[1:])
            require(
                field == "id" or field.endswith("_id"),
                "invalid_batch_reference",
                "Referências de lote só são permitidas em identificadores.",
            )
            require(
                index < len(previous) and isinstance(previous[index].get("id"), str),
                "invalid_batch_reference",
                "Referência deve apontar para entidade anterior do lote.",
            )
            return previous[index]["id"]
        return value

    @staticmethod
    def _allowed(payload: dict[str, Any], fields: set[str]) -> None:
        require(
            isinstance(payload, dict) and set(payload) <= fields,
            "invalid_payload",
            "Campos não permitidos nesta operação.",
        )

    @staticmethod
    def _record(
        session: Session, workspace: Workspace, kind: str, identifier: Any, *, active: bool = True
    ) -> Record:
        record = session.get(Record, identifier) if isinstance(identifier, str) else None
        require(
            record is not None and record.workspace_id == workspace.id and record.kind == kind,
            "not_found",
            "Referência não encontrada neste espaço financeiro.",
        )
        assert record is not None
        require(not active or record.data.get("active", True), "archived", "Referência arquivada.")
        return record

    @staticmethod
    def _tx(session: Session, workspace: Workspace, identifier: Any) -> Transaction:
        row = session.get(Transaction, identifier) if isinstance(identifier, str) else None
        require(
            row is not None and row.workspace_id == workspace.id,
            "not_found",
            "Movimentação não encontrada neste espaço financeiro.",
        )
        assert row is not None
        return row

    def _dispatch(
        self, session: Session, workspace: Workspace, operation: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        require(
            isinstance(operation, str) and isinstance(payload, dict),
            "invalid_payload",
            "Operação inválida.",
        )
        if operation == "configure_workspace":
            self._allowed(payload, {"name", "currency", "timezone"})
            if "name" in payload:
                name = payload["name"]
                require(
                    isinstance(name, str) and 0 < len(name.strip()) <= 200,
                    "invalid_name",
                    "Nome do espaço inválido.",
                )
                workspace.name = name.strip()
            if "timezone" in payload:
                try:
                    ZoneInfo(payload["timezone"])
                except (KeyError, ValueError, TypeError) as exc:
                    raise DomainError("invalid_timezone", "Fuso inválido.") from exc
                workspace.timezone = payload["timezone"]
            if "currency" in payload:
                self._currency(payload["currency"])
                if payload["currency"] != workspace.currency:
                    monetary_records = session.scalar(
                        select(Record)
                        .where(
                            Record.workspace_id == workspace.id,
                            Record.kind.in_(["account", "budget", "goal", "asset", "liability"]),
                        )
                        .limit(1)
                    )
                    financial_fact = session.scalar(
                        select(Transaction).where(Transaction.workspace_id == workspace.id).limit(1)
                    )
                    require(
                        monetary_records is None and financial_fact is None,
                        "currency_migration_required",
                        "Trocar moeda-base com histórico exige migração revisada.",
                    )
                workspace.currency = payload["currency"]
            return {"operation": operation, "id": workspace.id}
        if operation in {"duplicate_report", "duplicate_scenario"}:
            self._allowed(payload, {"id", "name"})
            kind = operation.removeprefix("duplicate_")
            source_config = self._record(session, workspace, kind, payload.get("id"))
            copied = {k: v for k, v in deepcopy(source_config.data).items() if k in FIELDS[kind]}
            copied["name"] = payload.get("name")
            return self._dispatch(session, workspace, f"create_{kind}", copied)
        require(
            operation in {"set_operations", "undo"} or not workspace.flags.get("mutations", False),
            "paused",
            "Alterações estão pausadas.",
        )
        if operation in {"create_transaction", "update_transaction"}:
            return self._write_transaction(
                session, workspace, payload, update=operation == "update_transaction"
            )
        if operation == "cancel_transaction":
            self._allowed(payload, {"id"})
            transaction = self._tx(session, workspace, payload.get("id"))
            refunds = session.scalars(
                select(Transaction).where(
                    Transaction.workspace_id == workspace.id, Transaction.type == "refund"
                )
            )
            require(
                not any(
                    r.status != "cancelled" and r.data.get("refund_of") == transaction.id
                    for r in refunds
                ),
                "has_refunds",
                "Cancele os reembolsos primeiro.",
            )
            transaction.status, transaction.revision = "cancelled", workspace.revision
            for installment in session.scalars(
                select(Record).where(
                    Record.workspace_id == workspace.id, Record.kind == "installment"
                )
            ):
                payments = installment.data.get("payments", [])
                reversal = sum(
                    payment["amount_minor"]
                    for payment in payments
                    if payment["transaction_id"] == transaction.id
                )
                if reversal:
                    data = deepcopy(installment.data)
                    data["payments"] = [
                        payment
                        for payment in payments
                        if payment["transaction_id"] != transaction.id
                    ]
                    data["paid_minor"] = data.get("paid_minor", 0) - reversal
                    data["settled"] = (
                        data["paid_minor"] + data.get("refunded_minor", 0) == data["amount_minor"]
                    )
                    installment.data, installment.revision = data, workspace.revision
                refunds = installment.data.get("refunds", [])
                refunded = sum(
                    refund["amount_minor"]
                    for refund in refunds
                    if refund["transaction_id"] == transaction.id
                )
                if refunded:
                    data = deepcopy(installment.data)
                    data["refunds"] = [
                        refund for refund in refunds if refund["transaction_id"] != transaction.id
                    ]
                    data["refunded_minor"] = data.get("refunded_minor", 0) - refunded
                    data["settled"] = (
                        data.get("paid_minor", 0) + data["refunded_minor"] == data["amount_minor"]
                    )
                    installment.data, installment.revision = data, workspace.revision
                if installment.data["transaction_id"] == transaction.id:
                    require(
                        not installment.data.get("paid_minor"),
                        "paid_commitment",
                        "Cancele ou corrija o pagamento vinculado antes da compra.",
                    )
                    installment.data = {**installment.data, "active": False}
                    installment.revision = workspace.revision
            return {"operation": operation, "id": transaction.id}
        if operation == "refund_transaction":
            self._allowed(payload, {"id", "amount_minor", "occurrence_date"})
            original = self._tx(session, workspace, payload.get("id"))
            return self._write_transaction(
                session,
                workspace,
                {
                    "type": "refund",
                    "amount_minor": payload.get("amount_minor"),
                    "occurrence_date": payload.get("occurrence_date"),
                    "currency": original.currency,
                    "refund_of": original.id,
                    "account_id": original.data.get("account_id"),
                    "description": f"Reembolso: {original.data.get('description', '')}",
                },
            )
        if operation == "settle_card":
            self._allowed(
                payload, {"account_id", "to_account_id", "amount_minor", "occurrence_date"}
            )
            card = self._record(session, workspace, "account", payload.get("to_account_id"))
            require(card.data["type"] == "card", "invalid_account", "Destino deve ser cartão.")
            result = self._write_transaction(session, workspace, {**payload, "type": "transfer"})
            transaction = self._tx(session, workspace, result["id"])
            transaction.data = {**transaction.data, "purpose": "card_settlement"}
            remaining = transaction.amount_minor
            installments = sorted(
                session.scalars(
                    select(Record).where(
                        Record.workspace_id == workspace.id, Record.kind == "installment"
                    )
                ),
                key=lambda item: (item.data["due_date"], item.data["number"]),
            )
            for installment in installments:
                purchase = self._tx(session, workspace, installment.data["transaction_id"])
                if (
                    purchase.data.get("account_id") != card.id
                    or purchase.status == "cancelled"
                    or not installment.data.get("active", True)
                ):
                    continue
                owed = (
                    installment.data["amount_minor"]
                    - installment.data.get("paid_minor", 0)
                    - installment.data.get("refunded_minor", 0)
                )
                paid = min(max(owed, 0), remaining)
                if paid:
                    data = deepcopy(installment.data)
                    data["paid_minor"] = data.get("paid_minor", 0) + paid
                    data["payments"] = [
                        *data.get("payments", []),
                        {"transaction_id": transaction.id, "amount_minor": paid},
                    ]
                    data["settled"] = (
                        data["paid_minor"] + data.get("refunded_minor", 0) == data["amount_minor"]
                    )
                    installment.data, installment.revision = data, workspace.revision
                    remaining -= paid
                if not remaining:
                    break
            transaction.data = {**transaction.data, "unallocated_payment_minor": remaining}
            return result
        if operation == "generate_recurrences":
            return self._generate_recurrences(session, workspace, payload)
        if operation == "advance_schedule":
            self._allowed(payload, {"id", "expected_next_run", "new_next_run"})
            schedule = self._record(session, workspace, "schedule", payload.get("id"))
            require(
                schedule.data["next_run"] == payload.get("expected_next_run"),
                "revision_conflict",
                "Rotina já avançou.",
            )
            updated = {**schedule.data, "next_run": payload.get("new_next_run")}
            self._validate_record(session, workspace, "schedule", updated, schedule.id)
            schedule.data, schedule.revision = updated, workspace.revision
            return {"operation": operation, "id": schedule.id}
        if operation == "set_operations":
            self._allowed(payload, {"flags"})
            flags = payload.get("flags")
            require(
                isinstance(flags, dict)
                and all(
                    k in {"ai", "audio", "excel", "sheets", "schedules", "mutations"}
                    and type(v) is bool
                    for k, v in flags.items()
                ),
                "invalid_flags",
                "Chaves inválidas.",
            )
            assert isinstance(flags, dict)
            workspace.flags = {**workspace.flags, **flags}
            return {"operation": operation, "flags": workspace.flags}
        if operation == "undo":
            return self._undo(session, workspace, payload)
        if operation == "reclassify_transactions":
            return self._reclassify(session, workspace, payload)
        parts = operation.split("_", 1)
        require(
            len(parts) == 2 and parts[1] in FIELDS, "unknown_operation", "Operação desconhecida."
        )
        verb, kind = parts
        require(
            verb in {"create", "update", "archive", "merge"},
            "unknown_operation",
            "Operação desconhecida.",
        )
        require(not workspace.flags.get("mutations", False), "paused", "Alterações estão pausadas.")
        if verb == "merge":
            require(kind in {"category", "area"}, "unknown_operation", "Mesclagem não permitida.")
            return self._merge(session, workspace, kind, payload)
        self._allowed(
            payload,
            {"id"} if verb == "archive" else FIELDS[kind] | ({"id"} if verb != "create" else set()),
        )
        if verb == "create":
            row = Record(workspace_id=workspace.id, kind=kind, data={}, revision=workspace.revision)
            session.add(row)
            data = payload
        else:
            row = self._record(session, workspace, kind, payload.get("id"), active=False)
            data = {**row.data, **{k: v for k, v in payload.items() if k != "id"}}
            if kind == "schedule" and "next_run" in payload:
                data.pop("anchor_day", None)
        if verb == "archive":
            data["active"] = False
        else:
            data.setdefault("active", True)
            self._validate_record(session, workspace, kind, data, row.id)
        row.data, row.revision = data, workspace.revision
        session.flush()
        return {"operation": operation, "id": row.id, "entity": {**data, "id": row.id}}

    def _validate_record(
        self,
        session: Session,
        workspace: Workspace,
        kind: str,
        data: dict[str, Any],
        identifier: str | None,
    ) -> None:
        if kind == "category":
            data.setdefault("type", "expense")
        if kind != "contribution":
            name = data.get("name")
            require(
                isinstance(name, str) and 0 < len(name.strip()) <= 200,
                "invalid_name",
                "Informe um nome com até 200 caracteres.",
            )
            assert isinstance(name, str)
            data["name"] = name.strip()
            for other in session.scalars(
                select(Record).where(Record.workspace_id == workspace.id, Record.kind == kind)
            ):
                if other.id != identifier and other.data.get("active", True):
                    same_parent = kind != "category" or (
                        other.data.get("parent_id") == data.get("parent_id")
                        and other.data.get("type") == data.get("type")
                    )
                    require(
                        not (
                            same_parent
                            and other.data.get("name", "").casefold() == data["name"].casefold()
                        ),
                        "name_collision",
                        "Nome já utilizado.",
                    )
                    if same_parent and kind in {"category", "area"}:
                        require(
                            isinstance(data.get("aliases", []), list),
                            "invalid_alias",
                            "Aliases inválidos.",
                        )
                        own_names = {
                            str(a).strip().casefold()
                            for a in [data["name"], *data.get("aliases", [])]
                        }
                        other_names = {
                            str(a).strip().casefold()
                            for a in [other.data.get("name", ""), *other.data.get("aliases", [])]
                        }
                        require(
                            not own_names.intersection(other_names),
                            "alias_collision",
                            "Nome ou alias já utilizado neste nível.",
                        )
        for key, target_kind in (
            ("area_id", "area"),
            ("project_id", "project"),
            ("category_id", "category"),
            ("account_id", "account"),
            ("goal_id", "goal"),
        ):
            if data.get(key):
                self._record(session, workspace, target_kind, data[key])
        if "aliases" in data:
            require(
                isinstance(data["aliases"], list)
                and all(isinstance(a, str) and a.strip() for a in data["aliases"]),
                "invalid_alias",
                "Aliases inválidos.",
            )
            data["aliases"] = list(dict.fromkeys(a.strip() for a in data["aliases"]))
        if kind == "category":
            require(
                data.get("type", "expense") in {"expense", "income"},
                "invalid_type",
                "Categoria deve ser receita ou despesa.",
            )
            data.setdefault("type", "expense")
            parent_id = data.get("parent_id")
            visited = {identifier}
            while parent_id:
                require(
                    parent_id not in visited, "category_cycle", "Categorias não podem formar ciclo."
                )
                visited.add(parent_id)
                parent = self._record(session, workspace, "category", parent_id)
                require(
                    parent.data["type"] == data["type"],
                    "invalid_parent",
                    "Categoria pai deve ter o mesmo tipo.",
                )
                parent_id = parent.data.get("parent_id")
            if identifier:
                for child in session.scalars(
                    select(Record).where(
                        Record.workspace_id == workspace.id, Record.kind == "category"
                    )
                ):
                    if child.data.get("parent_id") == identifier:
                        require(
                            child.data["type"] == data["type"],
                            "invalid_parent",
                            "A alteração deixaria subcategorias com tipo incompatível.",
                        )
        if kind == "account":
            data.setdefault("type", "bank")
            require(
                data["type"] in {"cash", "bank", "card", "liability"},
                "invalid_type",
                "Tipo de conta inválido.",
            )
            if data.get("opening_balance_minor") is not None:
                integer(data["opening_balance_minor"], "Saldo inicial", minimum=None)
                require(
                    bool(data.get("opening_date")),
                    "invalid_date",
                    "Saldo inicial exige data de referência.",
                )
            for key in ("closing_day", "due_day"):
                if key in data:
                    integer(data[key], key, minimum=1)
                    require(data[key] <= 31, "invalid_day", "Dia deve estar entre 1 e 31.")
        if kind == "budget":
            require(
                "amount_minor" in data, "invalid_amount", "Informe limite ou null para sem limite."
            )
            if data["amount_minor"] is not None:
                integer(data["amount_minor"], "Limite")
            require(
                data.get("period") in {"week", "month", "year", "custom"},
                "invalid_period",
                "Período do orçamento inválido.",
            )
            require(
                data.get("start_date") is not None, "invalid_date", "Informe início da vigência."
            )
            require(
                data["period"] != "custom" or bool(data.get("end_date")),
                "invalid_date",
                "Período personalizado exige data final.",
            )
            data.setdefault("basis", "accrual")
            require(data["basis"] in {"cash", "accrual"}, "invalid_basis", "Regime inválido.")
            data.setdefault("carryover", False)
            require(
                type(data["carryover"]) is bool, "invalid_payload", "Transporte deve ser booleano."
            )
            require(
                isinstance(data.get("thresholds", []), list), "invalid_rate", "Limiares inválidos."
            )
            data["thresholds"] = [decimal_string(v) for v in data.get("thresholds", ["0.8", "1"])]
            require(
                all(Decimal(v) > 0 for v in data["thresholds"]), "invalid_rate", "Limiar inválido."
            )
        if kind == "goal":
            integer(data.get("target_minor"), "Meta", minimum=1)
        if kind == "contribution":
            require(bool(data.get("goal_id")), "not_found", "Informe a meta.")
            integer(data.get("amount_minor"), "Contribuição", minimum=1)
            iso_date(data.get("occurrence_date"), "occurrence_date")
            goal = self._record(session, workspace, "goal", data["goal_id"])
            if data.get("account_id"):
                account = self._record(session, workspace, "account", data["account_id"])
                require(
                    account.data["currency"] == goal.data["currency"],
                    "currency_mismatch",
                    "Conta e meta devem ter a mesma moeda.",
                )
        if kind in {"asset", "liability"}:
            require("value_minor" in data, "invalid_amount", "Informe valor conhecido ou null.")
            if data["value_minor"] is not None:
                integer(data["value_minor"], "Valor")
            require(bool(data.get("as_of")), "invalid_date", "Informe data da avaliação.")
            if data.get("rate") is not None:
                data["rate"] = decimal_string(data["rate"])
            require(
                data.get("rate_period") in {None, "month", "year"},
                "invalid_rate",
                "Período da taxa deve ser mensal ou anual.",
            )
            for key in ("payment_minor", "months"):
                if data.get(key) is not None:
                    integer(data[key], key, minimum=1)
        if kind in {"schedule", "recurrence"}:
            require(
                data.get("frequency") in {"day", "week", "month", "year"},
                "invalid_frequency",
                "Frequência inválida.",
            )
            integer(data.setdefault("interval", 1), "Intervalo", minimum=1)
            require(
                data["interval"] <= 365, "invalid_frequency", "Intervalo máximo de 365 períodos."
            )
            data.setdefault("paused", False)
            require(type(data["paused"]) is bool, "invalid_payload", "Pausa deve ser booleana.")
            data.setdefault("timezone", workspace.timezone)
            try:
                ZoneInfo(data["timezone"])
            except (KeyError, ValueError) as exc:
                raise DomainError("invalid_timezone", "Fuso inválido.") from exc
            if kind == "recurrence":
                iso_date(data.get("next_date"), "next_date")
                for exception in data.setdefault("exceptions", []):
                    iso_date(exception, "exception")
                require(
                    isinstance(data.get("template"), dict), "invalid_payload", "Informe a cobrança."
                )
                self._validate_transaction(
                    session,
                    workspace,
                    deepcopy(data["template"]),
                    occurrence_override=data["next_date"],
                )
            else:
                require(
                    data.get("kind") in {"summary", "budget", "reminder", "subscription"},
                    "invalid_type",
                    "Tipo de rotina inválido.",
                )
                try:
                    instant = datetime.fromisoformat(data.get("next_run", ""))
                    require(
                        instant.tzinfo is not None, "invalid_date", "Horário exige fuso explícito."
                    )
                    data.setdefault(
                        "anchor_day", instant.astimezone(ZoneInfo(data["timezone"])).day
                    )
                except (ValueError, TypeError) as exc:
                    raise DomainError("invalid_date", "Horário da rotina inválido.") from exc
        if kind == "report":
            for field in ("rows", "columns", "metrics"):
                require(
                    isinstance(data.get(field, []), list)
                    and all(isinstance(v, str) for v in data.get(field, [])),
                    "invalid_report",
                    "Análise inválida.",
                )
            if "limit" in data:
                integer(data["limit"], "Limite de linhas", minimum=1)
                require(data["limit"] <= 10000, "invalid_report", "Limite máximo de 10000 linhas.")
            self._validate_filters(session, workspace, data.get("filters", {}))
            from app.analytics.reports import ReportDefinition

            definition = {
                key: data[key]
                for key in ("name", "rows", "columns", "metrics", "filters", "chart")
                if key in data
            }
            if data.get("order_by") is not None:
                definition["sort_by"] = data["order_by"]
            if data.get("limit") is not None:
                definition["max_cells"] = data["limit"]
            try:
                ReportDefinition.model_validate(definition)
            except ValueError as exc:
                raise DomainError(
                    "invalid_report", "Dimensões, métricas ou filtros da análise inválidos."
                ) from exc
        if kind == "scenario":
            assumptions = data.get("assumptions", {})
            require(
                isinstance(assumptions, dict)
                and set(assumptions)
                <= {
                    "income_minor",
                    "category_reductions",
                    "extra_expenses_minor",
                    "income_change_rate",
                    "extraordinary_expenses",
                    "name",
                    "start_date",
                    "end_date",
                    "horizon_days",
                    "include_recurrences",
                    "filters",
                    "debt_payment_minor",
                    "debt_periods",
                },
                "invalid_scenario",
                "Premissas não permitidas.",
            )
            for key in ("income_minor", "extra_expenses_minor"):
                if key in assumptions:
                    integer(assumptions[key], key)
            if "income_change_rate" in assumptions:
                value = assumptions["income_change_rate"]
                try:
                    rate = Decimal(str(value))
                    require(
                        not isinstance(value, (float, bool)) and rate.is_finite() and rate >= -1,
                        "invalid_rate",
                        "Variação de renda deve ser decimal e no mínimo -100%.",
                    )
                    assumptions["income_change_rate"] = str(rate)
                except InvalidOperation as exc:
                    raise DomainError("invalid_rate", "Variação de renda inválida.") from exc
            require(
                assumptions.get("income_minor") is None
                or Decimal(str(assumptions.get("income_change_rate", "0"))) == 0,
                "invalid_scenario",
                "Escolha renda mensal absoluta ou variação percentual.",
            )
            for key, maximum in (("horizon_days", 3660), ("debt_periods", 600)):
                if key in assumptions:
                    integer(assumptions[key], key, minimum=1)
                    require(
                        assumptions[key] <= maximum, "invalid_scenario", "Horizonte muito longo."
                    )
            require(
                type(assumptions.get("include_recurrences", True)) is bool,
                "invalid_scenario",
                "Recorrências exigem opção booleana.",
            )
            for key in ("start_date", "end_date"):
                if assumptions.get(key):
                    iso_date(assumptions[key], key)
            if assumptions.get("start_date") and assumptions.get("end_date"):
                require(
                    assumptions["start_date"] < assumptions["end_date"],
                    "invalid_scenario",
                    "Período do cenário inválido.",
                )
            self._validate_filters(session, workspace, assumptions.get("filters", {}))
            extraordinary = assumptions.get("extraordinary_expenses", [])
            require(
                isinstance(extraordinary, list) and len(extraordinary) <= 1000,
                "invalid_scenario",
                "Despesas extraordinárias inválidas.",
            )
            for extra in extraordinary:
                self._allowed(extra, {"date", "amount_minor", "currency", "description"})
                iso_date(extra.get("date"), "date")
                integer(extra.get("amount_minor"), "Despesa extraordinária")
                self._currency(extra.get("currency"))
                require(
                    isinstance(extra.get("description", ""), str),
                    "invalid_scenario",
                    "Descrição inválida.",
                )
            payments = assumptions.get("debt_payment_minor", {})
            require(
                isinstance(payments, dict), "invalid_scenario", "Pagamentos de dívida inválidos."
            )
            for liability_id, payment in payments.items():
                self._record(session, workspace, "liability", liability_id)
                integer(payment, "Pagamento")
            require(
                isinstance(assumptions.get("category_reductions", {}), dict),
                "invalid_scenario",
                "Reduções por categoria inválidas.",
            )
            for category_id, rate in assumptions.get("category_reductions", {}).items():
                self._record(session, workspace, "category", category_id)
                require(
                    Decimal(decimal_string(rate)) <= 1, "invalid_rate", "Redução deve ser até 100%."
                )
        for key in ("opening_date", "start_date", "end_date", "deadline", "as_of"):
            if data.get(key):
                data[key] = iso_date(data[key], key)
        if data.get("start_date") and data.get("end_date"):
            require(
                data["start_date"] <= data["end_date"], "invalid_date", "Fim anterior ao início."
            )
        if kind in {"account", "budget", "goal", "asset", "liability"}:
            self._currency(data.setdefault("currency", workspace.currency))

    def _validate_filters(self, session: Session, workspace: Workspace, filters: Any) -> None:
        from app.analytics.query import AnalyticsFilters

        try:
            parsed = AnalyticsFilters.model_validate(filters)
        except ValueError as exc:
            raise DomainError("invalid_filters", "Filtros inválidos.") from exc
        for field, kind in (
            ("category_ids", "category"),
            ("area_ids", "area"),
            ("project_ids", "project"),
            ("account_ids", "account"),
            ("tag_ids", "tag"),
        ):
            for identifier in getattr(parsed, field) or []:
                self._record(session, workspace, kind, identifier, active=False)

    @staticmethod
    def _currency(currency: Any) -> None:
        require(
            isinstance(currency, str)
            and len(currency) == 3
            and currency.isalpha()
            and currency.isupper(),
            "invalid_currency",
            "Moeda deve ser código ISO de três letras.",
        )
        currency_digits(currency)

    def _validate_transaction(
        self,
        session: Session,
        workspace: Workspace,
        data: dict[str, Any],
        *,
        occurrence_override: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, Any]:
        self._allowed(data, TX_FIELDS)
        integer(data.get("amount_minor"), "Valor", minimum=1)
        require(
            data.get("type") in {"expense", "income", "transfer", "refund"},
            "invalid_type",
            "Tipo de movimentação inválido.",
        )
        data["occurrence_date"] = iso_date(
            occurrence_override or data.get("occurrence_date"), "occurrence_date"
        )
        data.setdefault("competence_date", data["occurrence_date"])
        for key in ("competence_date", "settlement_date", "first_due_date", "fx_date"):
            if data.get(key):
                data[key] = iso_date(data[key], key)
        data.setdefault("currency", workspace.currency)
        self._currency(data["currency"])
        data.setdefault("status", "settled")
        require(data["status"] in {"pending", "settled"}, "invalid_status", "Status inválido.")
        if data["status"] == "settled":
            data.setdefault("settlement_date", data["occurrence_date"])
        data.setdefault("description", "")
        require(
            isinstance(data["description"], str) and len(data["description"]) <= 2000,
            "invalid_description",
            "Descrição inválida.",
        )
        for key in ("account_id", "to_account_id"):
            if data.get(key):
                account = self._record(session, workspace, "account", data[key])
                require(
                    account.data["currency"] == data["currency"],
                    "currency_mismatch",
                    "Conta e movimentação devem ter a mesma moeda.",
                )
        if data["type"] == "transfer":
            require(
                bool(data.get("account_id"))
                and bool(data.get("to_account_id"))
                and data["account_id"] != data["to_account_id"],
                "invalid_transfer",
                "Transferência exige duas contas diferentes.",
            )
            require(
                not data.get("allocations"),
                "invalid_transfer",
                "Transferência não tem rateio de consumo.",
            )
        else:
            require(
                not data.get("to_account_id"),
                "invalid_transfer",
                "Destino só vale em transferência.",
            )
        if data.get("fx_rate") is not None:
            data["fx_rate"] = decimal_string(data["fx_rate"], positive=True)
            require(
                bool(data.get("fx_date")) and bool(data.get("fx_source")),
                "invalid_fx",
                "Câmbio exige data e origem explícitas.",
            )
            source_scale = 10 ** currency_digits(data["currency"])
            base_scale = 10 ** currency_digits(workspace.currency)
            data["base_amount_minor"] = int(
                (
                    Decimal(data["amount_minor"])
                    / source_scale
                    * Decimal(data["fx_rate"])
                    * base_scale
                ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            )
            data["fx_rounding"] = "half_even"
            data["base_currency"] = workspace.currency
        if data["type"] == "refund":
            original = self._tx(session, workspace, data.get("refund_of"))
            require(
                original.type == "expense"
                and original.status != "cancelled"
                and original.currency == data["currency"],
                "invalid_refund",
                "Despesa original inválida.",
            )
            refunded = sum(
                row.amount_minor
                for row in session.scalars(
                    select(Transaction).where(
                        Transaction.workspace_id == workspace.id, Transaction.type == "refund"
                    )
                )
                if row.id != identifier
                and row.status != "cancelled"
                and row.data.get("refund_of") == original.id
            )
            require(
                refunded + data["amount_minor"] <= original.amount_minor,
                "refund_exceeds",
                "Reembolso supera o saldo da despesa original.",
            )
            if not data.get("allocations"):
                allocations = list(
                    session.scalars(
                        select(Allocation).where(Allocation.transaction_id == original.id)
                    )
                )
                if allocations:
                    remaining = data["amount_minor"]
                    parts = []
                    for index, allocation in enumerate(allocations):
                        amount = (
                            remaining
                            if index == len(allocations) - 1
                            else data["amount_minor"]
                            * allocation.amount_minor
                            // original.amount_minor
                        )
                        remaining -= amount
                        if amount:
                            parts.append({**allocation.data, "amount_minor": amount})
                    data["allocations"] = parts
        else:
            require(not data.get("refund_of"), "invalid_refund", "Vínculo de reembolso inválido.")
        allocations = data.setdefault("allocations", [])
        require(
            isinstance(allocations, list) and len(allocations) <= 100,
            "invalid_split",
            "Rateio inválido.",
        )
        for allocation in allocations:
            self._allowed(allocation, {"amount_minor", "category_id", "area_id", "project_id"})
            integer(allocation.get("amount_minor"), "Rateio", minimum=1)
            for key, kind in (
                ("category_id", "category"),
                ("area_id", "area"),
                ("project_id", "project"),
            ):
                if allocation.get(key):
                    record = self._record(session, workspace, kind, allocation[key])
                    if kind == "category":
                        expected = "expense" if data["type"] == "refund" else data["type"]
                        require(
                            record.data["type"] == expected,
                            "invalid_category",
                            "Categoria incompatível.",
                        )
                        allocation.setdefault("area_id", record.data.get("area_id"))
        require(
            not allocations or sum(a["amount_minor"] for a in allocations) == data["amount_minor"],
            "split_mismatch",
            "A soma dos rateios deve igualar o valor total.",
        )
        tags = data.setdefault("tags", [])
        require(isinstance(tags, list), "invalid_tags", "Tags inválidas.")
        for tag_id in tags:
            self._record(session, workspace, "tag", tag_id)
        data["tags"] = list(dict.fromkeys(tags))
        if data.get("installment_count") is not None:
            count = integer(data["installment_count"], "Parcelas", minimum=1)
            require(
                data["type"] == "expense" and count <= 600 and count <= data["amount_minor"],
                "invalid_installments",
                "Parcelamento inválido.",
            )
        return data

    def _write_transaction(
        self,
        session: Session,
        workspace: Workspace,
        payload: dict[str, Any],
        *,
        update: bool = False,
    ) -> dict[str, Any]:
        require(not workspace.flags.get("mutations", False), "paused", "Alterações estão pausadas.")
        existing = self._tx(session, workspace, payload.get("id")) if update else None
        original_account_id = existing.data.get("account_id") if existing else None
        original_anchor = existing.data.get("installment_anchor_day") if existing else None
        original_auto_due = existing.data.get("first_due_auto", False) if existing else False
        system_metadata = {
            key: existing.data[key]
            for key in ("recurrence_id", "recurrence_date", "source_key")
            if existing and key in existing.data
        }
        explicit_due_date = "first_due_date" in payload
        if existing:
            require(
                existing.data.get("purpose") != "card_settlement",
                "linked_payment",
                "Para corrigir pagamento de fatura, cancele e registre o valor correto.",
            )
            self._allowed(payload, TX_FIELDS | {"id"})
            base = self._transaction_dict(existing)
            base = {k: v for k, v in base.items() if k in TX_FIELDS}
            base["allocations"] = [
                {**a.data, "amount_minor": a.amount_minor}
                for a in session.scalars(
                    select(Allocation).where(Allocation.transaction_id == existing.id)
                )
            ]
            if (
                original_auto_due
                and not explicit_due_date
                and any(key in payload for key in ("occurrence_date", "account_id"))
            ):
                base.pop("first_due_date", None)
                original_anchor = None
            if (
                "amount_minor" in payload
                and "allocations" not in payload
                and len(base["allocations"]) == 1
            ):
                base["allocations"][0]["amount_minor"] = payload["amount_minor"]
            payload = {**base, **{k: v for k, v in payload.items() if k != "id"}}
            # Reducing/cancelling a refunded expense would break its reference.
            refunded = sum(
                r.amount_minor
                for r in session.scalars(
                    select(Transaction).where(
                        Transaction.workspace_id == workspace.id, Transaction.type == "refund"
                    )
                )
                if r.status != "cancelled" and r.data.get("refund_of") == existing.id
            )
            require(
                not refunded
                or (
                    payload.get("type") == "expense"
                    and payload.get("currency") == existing.currency
                    and payload.get("amount_minor", 0) >= refunded
                ),
                "has_refunds",
                "Há reembolsos vinculados.",
            )
        data = self._validate_transaction(
            session, workspace, payload, identifier=existing.id if existing else None
        )
        if data["type"] == "expense" and data.get("account_id"):
            account = self._record(session, workspace, "account", data["account_id"])
            if account.data["type"] == "card":
                data.setdefault("installment_count", 1)
        allocations = data.pop("allocations")
        row = existing or Transaction(
            workspace_id=workspace.id, data={}, revision=workspace.revision
        )
        row.type, row.amount_minor, row.currency = (
            data.pop("type"),
            data.pop("amount_minor"),
            data.pop("currency"),
        )
        row.occurrence_date, row.status = data.pop("occurrence_date"), data.pop("status")
        created_revision = (
            existing.data.get("created_revision", existing.revision)
            if existing
            else workspace.revision
        )
        created_sequence = (
            existing.data.get("created_sequence", created_revision)
            if existing
            else sum(
                1
                for _ in session.scalars(
                    select(Transaction.id).where(Transaction.workspace_id == workspace.id)
                )
            )
        )
        row.data, row.revision = (
            {
                **data,
                **system_metadata,
                "source": "command",
                "created_revision": created_revision,
                "created_sequence": created_sequence,
            },
            workspace.revision,
        )
        session.add(row)
        session.flush()
        session.execute(delete(Allocation).where(Allocation.transaction_id == row.id))
        for allocation in allocations:
            session.add(
                Allocation(
                    workspace_id=workspace.id,
                    transaction_id=row.id,
                    amount_minor=allocation["amount_minor"],
                    data={k: v for k, v in allocation.items() if k != "amount_minor"},
                )
            )
        old_installments = list(
            session.scalars(
                select(Record).where(
                    Record.workspace_id == workspace.id, Record.kind == "installment"
                )
            )
        )
        for installment in old_installments:
            previous_refunds = installment.data.get("refunds", [])
            credits = [refund for refund in previous_refunds if refund["transaction_id"] != row.id]
            if credits != previous_refunds:
                refunded = sum(refund["amount_minor"] for refund in credits)
                installment.data = {
                    **installment.data,
                    "refunds": credits,
                    "refunded_minor": refunded,
                    "settled": installment.data.get("paid_minor", 0) + refunded
                    == installment.data["amount_minor"],
                }
                installment.revision = workspace.revision
        if row.type == "refund" and row.data.get("account_id"):
            original = self._tx(session, workspace, row.data["refund_of"])
            account = self._record(session, workspace, "account", row.data["account_id"])
            if account.data["type"] == "card" and original.data.get("account_id") == account.id:
                remaining_refund = row.amount_minor
                for installment in sorted(old_installments, key=lambda item: item.data["number"]):
                    if installment.data[
                        "transaction_id"
                    ] != original.id or not installment.data.get("active", True):
                        continue
                    current = deepcopy(installment.data)
                    owed = (
                        current["amount_minor"]
                        - current.get("paid_minor", 0)
                        - current.get("refunded_minor", 0)
                    )
                    credit = min(max(owed, 0), remaining_refund)
                    if credit:
                        current["refunded_minor"] = current.get("refunded_minor", 0) + credit
                        current["refunds"] = [
                            *current.get("refunds", []),
                            {"transaction_id": row.id, "amount_minor": credit},
                        ]
                        current["settled"] = (
                            current.get("paid_minor", 0) + current["refunded_minor"]
                            == current["amount_minor"]
                        )
                        installment.data, installment.revision = current, workspace.revision
                        remaining_refund -= credit
                row.data = {**row.data, "unallocated_refund_minor": remaining_refund}
        previous_installments = {
            installment.data["number"]: installment
            for installment in old_installments
            if installment.data["transaction_id"] == row.id
        }
        count = data.get("installment_count")
        if count:
            automatic_due = not bool(data.get("first_due_date")) or (
                original_auto_due and not explicit_due_date
            )
            first = date.fromisoformat(data.get("first_due_date") or row.occurrence_date)
            due_anchor = first.day if explicit_due_date else int(original_anchor or first.day)
            if not data.get("first_due_date") and data.get("account_id"):
                account = self._record(session, workspace, "account", data["account_id"])
                if account.data["type"] == "card":
                    closing = account.data.get("closing_day")
                    due = account.data.get("due_day")
                    require(
                        bool(closing) and bool(due),
                        "card_calendar",
                        "Informe fechamento e vencimento.",
                    )
                    assert closing is not None and due is not None
                    closing, due = int(closing), int(due)
                    due_anchor = due
                    closing_date = first.replace(
                        day=min(closing, calendar.monthrange(first.year, first.month)[1])
                    )
                    month_offset = int(first > closing_date) + int(due <= closing)
                    due_month = add_months(first.replace(day=1), month_offset)
                    first = due_month.replace(
                        day=min(due, calendar.monthrange(due_month.year, due_month.month)[1])
                    )
            row.data = {
                **row.data,
                "first_due_date": first.isoformat(),
                "installment_anchor_day": due_anchor,
                "first_due_auto": automatic_due,
            }
            quotient, residue = divmod(row.amount_minor, count)
            for index in range(count):
                desired = {
                    "transaction_id": row.id,
                    "number": index + 1,
                    "total": count,
                    "amount_minor": quotient + int(index < residue),
                    "due_date": add_months(first, index, due_anchor).isoformat(),
                    "settled": False,
                    "paid_minor": 0,
                    "active": True,
                }
                candidate = previous_installments.pop(index + 1, None)
                if candidate is not None:
                    installment = candidate
                    paid = installment.data.get("paid_minor", 0)
                    refunded = installment.data.get("refunded_minor", 0)
                    require(
                        not (paid or refunded)
                        or (
                            original_account_id == data.get("account_id")
                            and all(
                                installment.data.get(key) == desired[key]
                                for key in ("amount_minor", "due_date", "total")
                            )
                        ),
                        "paid_commitment",
                        "Parcelas com pagamento não podem mudar valor, conta ou vencimento.",
                    )
                    installment.data = {
                        **installment.data,
                        **desired,
                        "paid_minor": paid,
                        "settled": paid + refunded == desired["amount_minor"],
                    }
                    installment.revision = workspace.revision
                else:
                    session.add(
                        Record(
                            workspace_id=workspace.id,
                            kind="installment",
                            revision=workspace.revision,
                            data=desired,
                        )
                    )
        for installment in previous_installments.values():
            require(
                not (installment.data.get("paid_minor") or installment.data.get("refunded_minor")),
                "paid_commitment",
                "Parcelas com pagamento não podem ser removidas.",
            )
            installment.data = {**installment.data, "active": False}
            installment.revision = workspace.revision
        return {
            "operation": "update_transaction" if update else "create_transaction",
            "id": row.id,
            "transaction": self._transaction_dict(row),
        }

    def _merge(
        self, session: Session, workspace: Workspace, kind: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._allowed(payload, {"id", "target_id"})
        source = self._record(session, workspace, kind, payload.get("id"))
        target = self._record(session, workspace, kind, payload.get("target_id"))
        require(source.id != target.id, "invalid_merge", "Escolha destinos diferentes.")
        if kind == "category":
            require(
                source.data["type"] == target.data["type"], "invalid_merge", "Tipos incompatíveis."
            )
            parent = target
            while parent.data.get("parent_id"):
                require(
                    parent.data["parent_id"] != source.id,
                    "category_cycle",
                    "Destino é descendente da origem.",
                )
                parent = self._record(session, workspace, kind, parent.data["parent_id"])
        reference = f"{kind}_id"
        for row in session.scalars(select(Record).where(Record.workspace_id == workspace.id)):
            changed = self._remap_reference(deepcopy(row.data), reference, source.id, target.id)
            if kind == "category" and row.kind == "scenario":
                reductions = changed.get("assumptions", {}).get("category_reductions", {})
                if source.id in reductions:
                    if target.id in reductions:
                        require(
                            Decimal(str(reductions[source.id]))
                            == Decimal(str(reductions[target.id])),
                            "merge_collision",
                            "Cenário tem premissas diferentes para as duas categorias.",
                        )
                    reductions[target.id] = reductions.pop(source.id)
            if (
                kind == "category"
                and row.kind == "category"
                and changed.get("parent_id") == source.id
            ):
                changed["parent_id"] = target.id
                self._validate_record(session, workspace, "category", changed, row.id)
            if changed != row.data:
                row.data, row.revision = changed, workspace.revision
        for allocation in session.scalars(
            select(Allocation).where(Allocation.workspace_id == workspace.id)
        ):
            if allocation.data.get(reference) == source.id:
                changed = {**allocation.data, reference: target.id}
                if kind == "category" and changed.get("area_id") == source.data.get("area_id"):
                    changed["area_id"] = target.data.get("area_id")
                allocation.data = changed
        source.data = {**source.data, "active": False, "merged_into": target.id}
        source.revision = workspace.revision
        return {"operation": f"merge_{kind}", "id": source.id, "target_id": target.id}

    @staticmethod
    def _remap_reference(value: Any, reference: str, source: str, target: str) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key == reference and item == source:
                    result[key] = target
                elif key == reference.removesuffix("_id") + "_ids" and isinstance(item, list):
                    values = [target if identifier == source else identifier for identifier in item]
                    result[key] = [
                        identifier
                        for index, identifier in enumerate(values)
                        if identifier not in values[:index]
                    ]
                else:
                    result[key] = FinanceService._remap_reference(item, reference, source, target)
            return result
        if isinstance(value, list):
            return [
                FinanceService._remap_reference(item, reference, source, target) for item in value
            ]
        return value

    def _reclassify(
        self, session: Session, workspace: Workspace, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._allowed(payload, {"category_id", "target_id", "start_date", "end_date"})
        source = self._record(
            session, workspace, "category", payload.get("category_id"), active=False
        )
        target = self._record(session, workspace, "category", payload.get("target_id"))
        require(
            source.data["type"] == target.data["type"], "invalid_category", "Tipos incompatíveis."
        )
        start, end = (
            iso_date(payload.get("start_date"), "start_date"),
            iso_date(payload.get("end_date"), "end_date"),
        )
        changed = set()
        for allocation in session.scalars(
            select(Allocation).where(Allocation.workspace_id == workspace.id)
        ):
            tx = self._tx(session, workspace, allocation.transaction_id)
            if (
                start <= tx.occurrence_date <= end
                and allocation.data.get("category_id") == source.id
            ):
                allocation.data = {
                    **allocation.data,
                    "category_id": target.id,
                    "area_id": target.data.get("area_id"),
                }
                tx.revision = workspace.revision
                changed.add(tx.id)
        return {"operation": "reclassify_transactions", "count": len(changed)}

    def _generate_recurrences(
        self, session: Session, workspace: Workspace, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._allowed(payload, {"through_date"})
        through = iso_date(payload.get("through_date"), "through_date")
        generated: list[str] = []
        existing_occurrences = {
            (tx.data.get("recurrence_id"), tx.data.get("recurrence_date"))
            for tx in session.scalars(
                select(Transaction).where(Transaction.workspace_id == workspace.id)
            )
            if tx.data.get("recurrence_id")
        }
        for recurrence in session.scalars(
            select(Record).where(Record.workspace_id == workspace.id, Record.kind == "recurrence")
        ):
            data = deepcopy(recurrence.data)
            if not data.get("active", True) or data.get("paused"):
                continue
            current = date.fromisoformat(data["next_date"])
            anchor = data.setdefault("anchor_day", current.day)
            limit = min(through, data.get("end_date") or through)
            while current.isoformat() <= limit:
                require(
                    len(generated) < 1000,
                    "too_many_occurrences",
                    "Gere no máximo 1000 ocorrências por vez.",
                )
                occurrence_key = (recurrence.id, current.isoformat())
                if (
                    current.isoformat() not in data.get("exceptions", [])
                    and occurrence_key not in existing_occurrences
                ):
                    result = self._write_transaction(
                        session,
                        workspace,
                        {**deepcopy(data["template"]), "occurrence_date": current.isoformat()},
                    )
                    tx = self._tx(session, workspace, result["id"])
                    tx.data = {
                        **tx.data,
                        "recurrence_id": recurrence.id,
                        "recurrence_date": current.isoformat(),
                    }
                    generated.append(tx.id)
                    existing_occurrences.add(occurrence_key)
                frequency, step = data["frequency"], data["interval"]
                current = (
                    current + timedelta(days=step * (7 if frequency == "week" else 1))
                    if frequency in {"day", "week"}
                    else add_months(current, step * (12 if frequency == "year" else 1), anchor)
                )
            data["next_date"] = current.isoformat()
            recurrence.data, recurrence.revision = data, workspace.revision
        return {"operation": "generate_recurrences", "ids": generated, "count": len(generated)}

    def _undo(
        self, session: Session, workspace: Workspace, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._allowed(payload, set())
        previous = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace.id)
            .order_by(AuditEvent.revision.desc())
            .limit(1)
        )
        require(
            previous is not None
            and previous.revision == workspace.revision - 1
            and "undo" not in previous.operation,
            "unsafe_undo",
            "Não há alteração segura para desfazer.",
        )
        assert previous is not None
        before = previous.before
        session.execute(delete(Allocation).where(Allocation.workspace_id == workspace.id))
        session.execute(delete(Transaction).where(Transaction.workspace_id == workspace.id))
        session.execute(delete(Record).where(Record.workspace_id == workspace.id))
        for kind, plural in KINDS.items():
            for original in before[plural]:
                data = {k: v for k, v in original.items() if k not in {"id", "revision"}}
                session.add(
                    Record(
                        id=original["id"],
                        workspace_id=workspace.id,
                        kind=kind,
                        data=data,
                        revision=workspace.revision,
                    )
                )
        for original in before["transactions"]:
            data = {
                k: v
                for k, v in original.items()
                if k
                not in {
                    "id",
                    "revision",
                    "type",
                    "amount_minor",
                    "currency",
                    "occurrence_date",
                    "status",
                }
            }
            session.add(
                Transaction(
                    id=original["id"],
                    workspace_id=workspace.id,
                    data=data,
                    revision=workspace.revision,
                    **{
                        k: original[k]
                        for k in {"type", "amount_minor", "currency", "occurrence_date", "status"}
                    },
                )
            )
        session.flush()
        for original in before["allocations"]:
            session.add(
                Allocation(
                    id=original["id"],
                    workspace_id=workspace.id,
                    transaction_id=original["transaction_id"],
                    amount_minor=original["amount_minor"],
                    data={
                        k: v
                        for k, v in original.items()
                        if k not in {"id", "transaction_id", "amount_minor"}
                    },
                )
            )
        workspace.flags = before.get("operations", {})
        workspace.name, workspace.currency, workspace.timezone = (
            before["name"],
            before["currency"],
            before["timezone"],
        )
        return {"operation": "undo", "undone_revision": previous.revision}
