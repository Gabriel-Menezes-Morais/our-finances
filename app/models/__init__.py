"""Persistent financial facts and durable processing state."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid() -> str:
    return str(uuid4())


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(200), default="Minhas finanças")
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    timezone: Mapped[str] = mapped_column(String(100), default="America/Sao_Paulo")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class Record(Base):
    """Validated dimension/configuration documents, independently addressable by UUID.

    Financial facts live in the separate transaction/allocation tables. Only the
    domain's explicit allowlisted commands may construct these documents.
    """

    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    occurrence_date: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class Allocation(Base):
    __tablename__ = "allocations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("workspace_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    revision: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(100))
    before: Mapped[dict[str, Any]] = mapped_column(JSON)
    after: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class AppliedCommand(Base):
    __tablename__ = "applied_commands"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    key: Mapped[str] = mapped_column(String(300))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class InboundEvent(Base):
    __tablename__ = "inbound_events"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    expected_revision: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (UniqueConstraint("dedupe_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    dedupe_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    available_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    lease_until: Mapped[str | None] = mapped_column(String(40))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    fence: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("workspace_id", "destination"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    destination: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[str | None] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(30), default="idle")


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(String(16000))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    units: Mapped[str] = mapped_column(String(100), default="0")
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
