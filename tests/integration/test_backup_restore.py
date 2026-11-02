"""Backups restore actual facts and keep external side effects suspended."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.analytics import compute
from app.db import Database
from app.domain import FinanceService
from app.jobs.store import DurableStore
from app.models import OutboxJob, PendingAction
from scripts.backup import create_backup, read_backup
from scripts.restore import restore_backup


def populated() -> tuple[Database, FinanceService]:
    database = Database("sqlite:///:memory:")
    database.initialize()
    service = FinanceService(database, 123)
    service.execute(
        "create_transaction",
        {
            "type": "expense",
            "amount_minor": 12345,
            "currency": "BRL",
            "occurrence_date": "2026-11-02",
            "description": "Descrição fictícia privada",
        },
        idempotency_key="fictional-expense",
    )
    return database, service


def test_encrypted_backup_restores_financial_facts_and_suspends_jobs(tmp_path: Path) -> None:
    database, service = populated()
    store = DurableStore(database)
    snapshot = service.snapshot()
    store.create_pending(snapshot["workspace_id"], 123, 123, {"actions": []}, snapshot["revision"])
    key = Fernet.generate_key()
    location = create_backup(database, tmp_path / "backup.ofbackup", key)
    assert "Descrição".encode() not in location.read_bytes()
    target = Database("sqlite:///:memory:")
    counts = restore_backup(location, target, key)
    restored = FinanceService(target, 123).snapshot()
    assert restored["transactions"] == snapshot["transactions"]
    assert restored["revision"] == snapshot["revision"]
    assert counts["transactions"] == 1
    assert compute(restored)["totals_by_currency"][0]["expense_minor"] == 12345
    assert restored["operations"]["schedules"] is True
    assert DurableStore(target).claim("should-not-run") is None
    with target.session() as session:
        assert session.scalars(select(PendingAction.status)).all() == ["cancelled"]
        assert set(session.scalars(select(OutboxJob.status)).all()) == {"uncertain"}


def test_backup_wrong_key_and_modified_ciphertext_are_rejected(tmp_path: Path) -> None:
    database, _ = populated()
    key = Fernet.generate_key()
    location = create_backup(database, tmp_path / "backup.ofbackup", key)
    with pytest.raises(ValueError, match="Chave inválida"):
        read_backup(location, Fernet.generate_key())
    payload = bytearray(location.read_bytes())
    payload[50] ^= 1
    location.write_bytes(payload)
    with pytest.raises(ValueError, match="backup alterado"):
        read_backup(location, key)


def test_restore_refuses_nonempty_destination_without_changing_it(tmp_path: Path) -> None:
    database, service = populated()
    key = Fernet.generate_key()
    location = create_backup(database, tmp_path / "backup.ofbackup", key)
    before = service.snapshot()
    with pytest.raises(ValueError, match="vazio e isolado"):
        restore_backup(location, database, key)
    assert service.snapshot()["transactions"] == before["transactions"]
    assert service.snapshot()["revision"] == before["revision"]


def test_backup_refuses_overwriting_an_existing_copy(tmp_path: Path) -> None:
    database, _ = populated()
    key = Fernet.generate_key()
    location = create_backup(database, tmp_path / "backup.ofbackup", key)
    original = location.read_bytes()
    with pytest.raises(ValueError, match="já existe"):
        create_backup(database, location, key)
    assert location.read_bytes() == original
