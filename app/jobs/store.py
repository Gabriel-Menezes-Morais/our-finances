"""Durable inbox, confirmations, work leases and publication fencing."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select

from app.db import Database
from app.domain.service import decimal_string, integer, require
from app.models import (
    ConversationTurn,
    InboundEvent,
    OutboxJob,
    PendingAction,
    Publication,
    Record,
    UsageRecord,
    Workspace,
    utcnow,
)


def future(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


class DurableStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def persist_inbound(
        self, source: str, external_id: str, owner_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        require(bool(source) and bool(external_id), "invalid_event", "Origem do evento inválida.")
        with self.database.session() as session:
            # PostgreSQL advisory transaction lock prevents first-insert races for
            # duplicate events without exposing event contents in SQL.
            if self.database.engine.dialect.name == "postgresql":
                from hashlib import sha256

                from sqlalchemy import text

                lock = int.from_bytes(
                    sha256(f"{source}:{external_id}".encode()).digest()[:8], "big", signed=True
                )
                session.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
            row = session.scalar(
                select(InboundEvent).where(
                    InboundEvent.source == source, InboundEvent.external_id == external_id
                )
            )
            created = row is None
            if row is None:
                row = InboundEvent(
                    source=source, external_id=external_id, owner_id=owner_id, payload=payload
                )
                session.add(row)
                session.flush()
            require(row.owner_id == owner_id, "forbidden", "Evento pertence a outro usuário.")
            return {"id": row.id, "created": created, "status": row.status}

    def get_inbound(self, event_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.get(InboundEvent, event_id)
            return self._inbound(row) if row else None

    @staticmethod
    def _inbound(row: InboundEvent) -> dict[str, Any]:
        return {
            "id": row.id,
            "source": row.source,
            "external_id": row.external_id,
            "owner_id": row.owner_id,
            "payload": row.payload,
            "status": row.status,
        }

    def pending_inbounds(self, source: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as session:
            return [
                self._inbound(row)
                for row in session.scalars(
                    select(InboundEvent)
                    .where(InboundEvent.source == source, InboundEvent.status == "pending")
                    .order_by(InboundEvent.created_at)
                    .limit(limit)
                )
            ]

    def mark_inbound(self, event_id: str, status: str) -> None:
        require(status in {"pending", "processed", "failed"}, "invalid_status", "Status inválido.")
        with self.database.session() as session:
            row = session.get(InboundEvent, event_id)
            require(row is not None, "not_found", "Evento não encontrado.")
            assert row is not None
            row.status = status

    def create_pending(
        self,
        workspace_id: str,
        owner_id: int,
        chat_id: int,
        payload: dict[str, Any],
        expected_revision: int,
        ttl_seconds: int = 900,
    ) -> str:
        require(0 < ttl_seconds <= 86400, "invalid_expiry", "Validade inválida.")
        with self.database.session() as session:
            workspace = session.get(Workspace, workspace_id)
            require(
                workspace is not None and workspace.owner_id == owner_id,
                "forbidden",
                "Sem permissão para esta confirmação.",
            )
            row = PendingAction(
                workspace_id=workspace_id,
                owner_id=owner_id,
                chat_id=chat_id,
                payload=payload,
                expected_revision=expected_revision,
                expires_at=future(ttl_seconds),
            )
            session.add(row)
            session.flush()
            return row.id

    def get_pending(self, token: str, owner_id: int, chat_id: int) -> dict[str, Any]:
        with self.database.session() as session:
            row = session.get(PendingAction, token)
            require(
                row is not None and row.owner_id == owner_id and row.chat_id == chat_id,
                "forbidden",
                "Confirmação não autorizada para este usuário/chat.",
            )
            assert row is not None
            require(row.expires_at > utcnow(), "expired", "Confirmação expirada. Peça nova prévia.")
            require(row.status in {"pending", "confirmed"}, "resolved", "Confirmação já encerrada.")
            return {
                "id": row.id,
                "workspace_id": row.workspace_id,
                "owner_id": row.owner_id,
                "chat_id": row.chat_id,
                "payload": row.payload,
                "expected_revision": row.expected_revision,
                "status": row.status,
                "expires_at": row.expires_at,
            }

    def resolve_pending(
        self, token: str, owner_id: int, chat_id: int, status: str = "confirmed"
    ) -> None:
        require(
            status in {"confirmed", "rejected", "cancelled"}, "invalid_status", "Status inválido."
        )
        with self.database.session() as session:
            row = session.scalar(
                select(PendingAction).where(PendingAction.id == token).with_for_update()
            )
            require(
                row is not None and row.owner_id == owner_id and row.chat_id == chat_id,
                "forbidden",
                "Confirmação não autorizada.",
            )
            assert row is not None
            require(row.status in {"pending", status}, "resolved", "Confirmação já encerrada.")
            row.status = status

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        dedupe_key: str,
        workspace_id: str | None = None,
        available_at: str | None = None,
    ) -> str:
        with self.database.session() as session:
            existing = session.scalar(select(OutboxJob).where(OutboxJob.dedupe_key == dedupe_key))
            if existing:
                require(
                    existing.kind == kind and existing.payload == payload,
                    "idempotency_conflict",
                    "Job já existe com conteúdo diferente.",
                )
                return existing.id
            row = OutboxJob(
                kind=kind,
                payload=payload,
                dedupe_key=dedupe_key,
                workspace_id=workspace_id,
                available_at=available_at or utcnow(),
            )
            session.add(row)
            session.flush()
            return row.id

    def get_job_by_key(self, dedupe_key: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.scalar(select(OutboxJob).where(OutboxJob.dedupe_key == dedupe_key))
            return (
                {
                    "id": row.id,
                    "kind": row.kind,
                    "payload": row.payload,
                    "status": row.status,
                    "fence": row.fence,
                }
                if row
                else None
            )

    def claim(
        self,
        worker_id: str,
        *,
        kinds: list[str] | None = None,
        lease_seconds: int = 60,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        require(bool(worker_id) and lease_seconds > 0, "invalid_lease", "Lease inválida.")
        with self.database.session() as session:
            now = utcnow()
            query = select(OutboxJob).where(
                OutboxJob.available_at <= now,
                or_(
                    OutboxJob.status == "pending",
                    (OutboxJob.status == "running") & (OutboxJob.lease_until < now),
                ),
            )
            if kinds:
                query = query.where(OutboxJob.kind.in_(kinds))
            if workspace_id is not None:
                query = query.where(OutboxJob.workspace_id == workspace_id)
            row = session.scalar(
                query.order_by(OutboxJob.created_at, OutboxJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status, row.lease_owner, row.lease_until = (
                "running",
                worker_id,
                future(lease_seconds),
            )
            row.fence += 1
            row.attempts += 1
            return {
                "id": row.id,
                "kind": row.kind,
                "payload": row.payload,
                "workspace_id": row.workspace_id,
                "fence": row.fence,
                "attempts": row.attempts,
                "lease_until": row.lease_until,
            }

    @staticmethod
    def _assert_lease(row: OutboxJob | None, worker_id: str, fence: int) -> OutboxJob:
        require(
            row is not None
            and row.status == "running"
            and row.lease_owner == worker_id
            and row.fence == fence
            and (row.lease_until or "") > utcnow(),
            "stale_lease",
            "Lease expirada ou substituída; reconcilie antes de escrever.",
        )
        assert row is not None
        return row

    def complete(self, job_id: str, worker_id: str, fence: int) -> None:
        with self.database.session() as session:
            row = self._assert_lease(
                session.scalar(select(OutboxJob).where(OutboxJob.id == job_id).with_for_update()),
                worker_id,
                fence,
            )
            row.status, row.lease_until = "completed", None

    def renew(self, job_id: str, worker_id: str, fence: int, lease_seconds: int = 60) -> None:
        with self.database.session() as session:
            row = self._assert_lease(
                session.scalar(select(OutboxJob).where(OutboxJob.id == job_id).with_for_update()),
                worker_id,
                fence,
            )
            row.lease_until = future(lease_seconds)

    def fail(
        self,
        job_id: str,
        worker_id: str,
        fence: int,
        error: str,
        retry_seconds: int = 30,
        uncertain: bool = False,
    ) -> None:
        with self.database.session() as session:
            row = self._assert_lease(
                session.scalar(select(OutboxJob).where(OutboxJob.id == job_id).with_for_update()),
                worker_id,
                fence,
            )
            # Callers pass only a safe error code, never provider response bodies.
            row.last_error = error[:500]
            row.status = "uncertain" if uncertain else "pending"
            row.available_at, row.lease_until = future(retry_seconds), None

    def reconcile(self, job_id: str, *, completed: bool) -> None:
        with self.database.session() as session:
            row = session.get(OutboxJob, job_id)
            require(
                row is not None and row.status == "uncertain",
                "invalid_state",
                "Job não está aguardando reconciliação.",
            )
            assert row is not None
            row.status = "completed" if completed else "pending"
            row.available_at = utcnow()

    def pending_counts(self) -> dict[str, int]:
        with self.database.session() as session:
            result: dict[str, int] = {}
            for status in session.scalars(select(OutboxJob.status)):
                result[status] = result.get(status, 0) + 1
            return result

    def publication(self, workspace_id: str, destination: str) -> dict[str, Any]:
        with self.database.session() as session:
            row = session.scalar(
                select(Publication).where(
                    Publication.workspace_id == workspace_id, Publication.destination == destination
                )
            )
            return (
                {"revision": row.revision, "fence": row.fence, "evidence": row.evidence}
                if row
                else {"revision": 0, "fence": 0, "evidence": {}}
            )

    def acquire_writer(
        self, workspace_id: str, destination: str, worker_id: str, lease_seconds: int = 60
    ) -> dict[str, Any] | None:
        """One writer per workbook. Expired external writes require reconciliation."""
        with self.database.session() as session:
            workspace = session.scalar(
                select(Workspace).where(Workspace.id == workspace_id).with_for_update()
            )
            require(workspace is not None, "not_found", "Espaço não encontrado.")
            row = session.scalar(
                select(Publication)
                .where(
                    Publication.workspace_id == workspace_id, Publication.destination == destination
                )
                .with_for_update()
            )
            if row is None:
                row = Publication(
                    workspace_id=workspace_id,
                    destination=destination,
                    revision=0,
                    fence=0,
                    evidence={},
                    state="idle",
                )
                session.add(row)
            if row.state == "running":
                if (row.lease_until or "") <= utcnow():
                    row.state = "uncertain"
                return None
            if row.state == "uncertain":
                return None
            row.fence += 1
            row.state, row.lease_owner, row.lease_until = (
                "running",
                worker_id,
                future(lease_seconds),
            )
            return {"fence": row.fence, "revision": row.revision, "lease_until": row.lease_until}

    def finish_writer(
        self,
        workspace_id: str,
        destination: str,
        worker_id: str,
        fence: int,
        revision: int,
        evidence: dict[str, Any],
    ) -> None:
        with self.database.session() as session:
            row = session.scalar(
                select(Publication)
                .where(
                    Publication.workspace_id == workspace_id, Publication.destination == destination
                )
                .with_for_update()
            )
            require(
                row is not None
                and row.state == "running"
                and row.lease_owner == worker_id
                and row.fence == fence
                and (row.lease_until or "") > utcnow(),
                "stale_lease",
                "Escritor substituído ou expirado; reconcilie o destino.",
            )
            assert row is not None
            require(revision >= row.revision, "stale_revision", "Publicação obsoleta.")
            row.revision, row.evidence, row.state = revision, evidence, "idle"
            row.lease_until = None

    def reconcile_writer(
        self, workspace_id: str, destination: str, revision: int, evidence: dict[str, Any]
    ) -> None:
        with self.database.session() as session:
            row = session.scalar(
                select(Publication)
                .where(
                    Publication.workspace_id == workspace_id, Publication.destination == destination
                )
                .with_for_update()
            )
            require(
                row is not None
                and (
                    row.state == "uncertain"
                    or (row.state == "running" and (row.lease_until or "") <= utcnow())
                ),
                "invalid_state",
                "Destino não está aguardando reconciliação.",
            )
            assert row is not None
            require(revision >= row.revision, "stale_revision", "Evidência obsoleta.")
            row.revision, row.evidence, row.state = revision, evidence, "idle"
            row.lease_until = None

    def due_schedules(self, as_of: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        instant = datetime.fromisoformat(as_of or utcnow())
        require(instant.tzinfo is not None, "invalid_date", "Horário exige fuso explícito.")
        with self.database.session() as session:
            result = []
            for row in session.scalars(select(Record).where(Record.kind == "schedule")):
                if not row.data.get("active", True) or row.data.get("paused"):
                    continue
                workspace = session.get(Workspace, row.workspace_id)
                assert workspace is not None
                if workspace.flags.get("schedules"):
                    continue
                if datetime.fromisoformat(row.data["next_run"]) <= instant:
                    result.append(
                        {
                            **row.data,
                            "id": row.id,
                            "workspace_id": workspace.id,
                            "owner_id": workspace.owner_id,
                            "expected_revision": workspace.revision,
                        }
                    )
            return sorted(result, key=lambda row: row["next_run"])[:limit]

    def advance_schedule(self, schedule_id: str, expected_next_run: str, new_next_run: str) -> bool:
        from app.domain import FinanceService

        with self.database.session() as session:
            row = session.get(Record, schedule_id)
            require(
                row is not None and row.kind == "schedule", "not_found", "Rotina não encontrada."
            )
            assert row is not None
            if row.data["next_run"] != expected_next_run:
                return False
            workspace = session.get(Workspace, row.workspace_id)
            assert workspace is not None
            owner_id, workspace_id, revision = workspace.owner_id, workspace.id, workspace.revision
        FinanceService(self.database, owner_id, workspace_id).execute(
            "advance_schedule",
            {
                "id": schedule_id,
                "expected_next_run": expected_next_run,
                "new_next_run": new_next_run,
            },
            idempotency_key=f"advance:{schedule_id}:{expected_next_run}",
            expected_revision=revision,
        )
        return True

    def record_publication(
        self,
        workspace_id: str,
        destination: str,
        revision: int,
        fence: int,
        evidence: dict[str, Any],
    ) -> bool:
        with self.database.session() as session:
            workspace = session.scalar(
                select(Workspace).where(Workspace.id == workspace_id).with_for_update()
            )
            require(workspace is not None, "not_found", "Espaço não encontrado.")
            row = session.scalar(
                select(Publication)
                .where(
                    Publication.workspace_id == workspace_id, Publication.destination == destination
                )
                .with_for_update()
            )
            if row is None:
                row = Publication(
                    workspace_id=workspace_id,
                    destination=destination,
                    revision=0,
                    fence=0,
                    evidence={},
                )
                session.add(row)
            if revision < row.revision or fence < row.fence:
                return False
            row.revision, row.fence, row.evidence = revision, fence, evidence
            return True

    def record_turn(
        self, owner_id: int, role: str, text: str, workspace_id: str | None = None
    ) -> None:
        require(role in {"user", "assistant"}, "invalid_role", "Papel inválido.")
        with self.database.session() as session:
            if workspace_id:
                workspace = session.get(Workspace, workspace_id)
                require(
                    workspace is not None and workspace.owner_id == owner_id,
                    "forbidden",
                    "Espaço não autorizado.",
                )
            session.add(
                ConversationTurn(
                    owner_id=owner_id, role=role, text=text[:16000], workspace_id=workspace_id
                )
            )

    def recent_turns(self, owner_id: int, limit: int = 8) -> list[dict[str, str]]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(ConversationTurn)
                    .where(ConversationTurn.owner_id == owner_id)
                    .order_by(ConversationTurn.created_at.desc())
                    .limit(min(max(limit, 1), 32))
                )
            )
            return [{"role": r.role, "text": r.text} for r in reversed(rows)]

    def record_usage(
        self,
        owner_id: int,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        units: Any = 0,
    ) -> None:
        integer(input_tokens, "Tokens de entrada")
        integer(output_tokens, "Tokens de saída")
        with self.database.session() as session:
            session.add(
                UsageRecord(
                    owner_id=owner_id,
                    provider=provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    units=decimal_string(units),
                )
            )

    def usage_summary(self, owner_id: int) -> dict[str, Any]:
        with self.database.session() as session:
            result: dict[str, Any] = {}
            for row in session.scalars(select(UsageRecord).where(UsageRecord.owner_id == owner_id)):
                item = result.setdefault(
                    row.provider, {"input_tokens": 0, "output_tokens": 0, "units": "0", "calls": 0}
                )
                item["input_tokens"] += row.input_tokens
                item["output_tokens"] += row.output_tokens
                item["units"] = str(Decimal(item["units"]) + Decimal(row.units))
                item["calls"] += 1
            return result
