"""Clock-based schedules remain scoped, idempotent and recoverable after restart."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import Database
from app.domain import FinanceService
from app.jobs.scheduler import Scheduler, next_run
from app.jobs.store import DurableStore
from app.models import OutboxJob


def test_scheduler_enqueues_once_and_skips_missed_occurrences() -> None:
    database = Database("sqlite:///:memory:")
    database.initialize()
    service = FinanceService(database, 123)
    service.execute(
        "create_schedule",
        {
            "name": "Resumo semanal",
            "kind": "summary",
            "frequency": "week",
            "next_run": "2026-01-01T09:00:00-03:00",
        },
        idempotency_key="weekly",
    )
    store = DurableStore(database)
    scheduler = Scheduler(service, store)
    instant = datetime(2026, 11, 2, 12, tzinfo=UTC)
    assert scheduler.tick(instant) == 1
    assert Scheduler(FinanceService(database, 123), store).tick(instant) == 0
    with database.session() as session:
        jobs = session.scalars(select(OutboxJob).where(OutboxJob.kind == "scheduled_report")).all()
        assert len(jobs) == 1
        assert jobs[0].payload["owner_id"] == 123
    following = service.snapshot()["schedules"][0]["next_run"]
    assert datetime.fromisoformat(following) > instant


def test_scheduler_does_not_enqueue_another_owners_due_schedule() -> None:
    database = Database("sqlite:///:memory:")
    database.initialize()
    other = FinanceService(database, 999)
    other.execute(
        "create_schedule",
        {
            "name": "Outro usuário",
            "kind": "summary",
            "frequency": "day",
            "next_run": "2026-01-01T09:00:00-03:00",
        },
        idempotency_key="other-schedule",
    )
    current = FinanceService(database, 123)
    assert Scheduler(current, DurableStore(database)).tick(datetime(2026, 11, 2, tzinfo=UTC)) == 0
    with database.session() as session:
        assert (
            session.scalars(select(OutboxJob).where(OutboxJob.kind == "scheduled_report")).all()
            == []
        )


def test_month_end_next_schedule_preserves_anchor_within_catchup() -> None:
    result = next_run(
        "2026-01-31T09:00:00-03:00",
        "month",
        1,
        "America/Sao_Paulo",
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert result == "2026-03-31T12:00:00+00:00"
