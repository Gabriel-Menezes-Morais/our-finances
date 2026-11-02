from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db import Database
from app.domain import DomainError, FinanceService
from app.jobs.store import DurableStore
from app.models import OutboxJob, Publication


def setup_store(tmp_path: Path) -> tuple[Database, DurableStore, str]:
    database = Database(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    database.initialize()
    workspace_id = FinanceService(database, 123).snapshot()["workspace_id"]
    return database, DurableStore(database), workspace_id


def test_inbox_pending_and_conversation_survive_restart(tmp_path: Path) -> None:
    database, store, workspace_id = setup_store(tmp_path)
    event = store.persist_inbound("telegram:bot1", "42", 123, {"message": "fictício"})
    assert store.persist_inbound("telegram:bot1", "42", 123, {})["created"] is False
    token = store.create_pending(workspace_id, 123, 123, {"actions": []}, 0)
    assert len(token) <= 40
    store.record_turn(123, "user", "Informação fictícia", workspace_id)
    store.record_usage(123, "openai", 10, 2)
    database.close()
    reopened = DurableStore(Database(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"))
    assert reopened.get_inbound(event["id"])["payload"] == {"message": "fictício"}
    assert reopened.get_pending(token, 123, 123)["expected_revision"] == 0
    assert reopened.recent_turns(123)[0]["role"] == "user"
    assert reopened.usage_summary(123)["openai"]["input_tokens"] == 10
    with pytest.raises(DomainError):
        reopened.get_pending(token, 456, 123)
    with pytest.raises(DomainError):
        reopened.get_pending(token, 123, 456)


def test_job_lease_fencing_retry_and_uncertain_reconciliation(tmp_path: Path) -> None:
    database, store, workspace_id = setup_store(tmp_path)
    job_id = store.enqueue("test", {}, dedupe_key="job", workspace_id=workspace_id)
    assert store.enqueue("test", {}, dedupe_key="job", workspace_id=workspace_id) == job_id
    first = store.claim("worker1")
    assert first
    assert store.claim("worker2") is None
    with database.session() as session:
        row = session.get(OutboxJob, job_id)
        row.lease_until = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    second = store.claim("worker2")
    assert second and second["fence"] > first["fence"]
    with pytest.raises(DomainError):
        store.complete(job_id, "worker1", first["fence"])
    store.fail(job_id, "worker2", second["fence"], "provider_timeout", uncertain=True)
    assert store.claim("worker3") is None
    store.reconcile(job_id, completed=False)
    third = store.claim("worker3")
    assert third
    store.complete(job_id, "worker3", third["fence"])
    assert store.pending_counts() == {"completed": 1}


def test_publication_revision_never_regresses(tmp_path: Path) -> None:
    _, store, workspace_id = setup_store(tmp_path)
    assert store.record_publication(workspace_id, "excel", 11, 2, {"verified": True})
    assert not store.record_publication(workspace_id, "excel", 10, 3, {})
    assert not store.record_publication(workspace_id, "excel", 12, 1, {})
    assert store.publication(workspace_id, "excel")["revision"] == 11


def test_writer_expiry_requires_reconciliation_and_rejects_old_writer(tmp_path: Path) -> None:
    database, store, workspace_id = setup_store(tmp_path)
    first = store.acquire_writer(workspace_id, "workbook:1", "writer1")
    assert first
    assert store.acquire_writer(workspace_id, "workbook:1", "writer2") is None
    with database.session() as session:
        publication = session.query(Publication).one()
        publication.lease_until = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert store.acquire_writer(workspace_id, "workbook:1", "writer2") is None
    with pytest.raises(DomainError):
        store.finish_writer(workspace_id, "workbook:1", "writer1", first["fence"], 1, {})
    store.reconcile_writer(workspace_id, "workbook:1", 1, {"verified": True})
    second = store.acquire_writer(workspace_id, "workbook:1", "writer2")
    assert second and second["fence"] > first["fence"]
    store.finish_writer(workspace_id, "workbook:1", "writer2", second["fence"], 2, {})
    assert store.publication(workspace_id, "workbook:1")["revision"] == 2


def test_due_schedule_advance_is_audited_and_survives_restart(tmp_path: Path) -> None:
    database, store, workspace_id = setup_store(tmp_path)
    service = FinanceService(database, 123, workspace_id)
    schedule = service.execute(
        "create_schedule",
        {
            "name": "Resumo",
            "kind": "summary",
            "frequency": "week",
            "next_run": "2026-01-01T09:00:00-03:00",
        },
        idempotency_key="schedule",
    )["id"]
    assert store.due_schedules("2026-01-01T11:00:00+00:00") == []
    assert store.due_schedules("2026-01-01T13:00:00+00:00")[0]["id"] == schedule
    assert store.advance_schedule(
        schedule, "2026-01-01T09:00:00-03:00", "2026-01-08T09:00:00-03:00"
    )
    assert not store.advance_schedule(
        schedule, "2026-01-01T09:00:00-03:00", "2026-01-08T09:00:00-03:00"
    )
    assert service.snapshot()["revision"] == 2


def test_schedule_anchor_survives_advances_and_workspace_job_claim_is_scoped(
    tmp_path: Path,
) -> None:
    database, store, workspace_id = setup_store(tmp_path)
    service = FinanceService(database, 123, workspace_id)
    schedule = service.execute(
        "create_schedule",
        {
            "name": "Mensal",
            "kind": "summary",
            "frequency": "month",
            "next_run": "2026-01-31T09:00:00-03:00",
        },
        idempotency_key="anchor",
    )["id"]
    store.advance_schedule(schedule, "2026-01-31T09:00:00-03:00", "2026-02-28T09:00:00-03:00")
    assert service.snapshot()["schedules"][0]["anchor_day"] == 31
    service.execute(
        "update_schedule",
        {"id": schedule, "next_run": "2026-03-15T09:00:00-03:00"},
        idempotency_key="reschedule",
    )
    assert service.snapshot()["schedules"][0]["anchor_day"] == 15
    other_workspace = FinanceService(database, 456).snapshot()["workspace_id"]
    foreign = store.enqueue("foreign", {}, dedupe_key="foreign", workspace_id=other_workspace)
    assert store.claim("own", kinds=["foreign"], workspace_id=workspace_id) is None
    assert store.claim("other", kinds=["foreign"], workspace_id=other_workspace)["id"] == foreign
