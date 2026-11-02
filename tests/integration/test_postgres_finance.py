"""Opt-in tests against an explicitly supplied local sandbox PostgreSQL URL.

Each test owns a generated schema; existing workspace tables are never modified.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.db import Database
from app.domain import DomainError, FinanceService
from app.jobs.store import DurableStore
from app.models import AuditEvent, Base, OutboxJob

pytestmark = pytest.mark.skipif(
    not os.getenv("OUR_FINANCES_TEST_POSTGRES_URL"),
    reason="PostgreSQL sandbox URL not explicitly supplied",
)


@pytest.fixture
def postgres() -> Any:
    url = os.environ["OUR_FINANCES_TEST_POSTGRES_URL"]
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost", "db"}, "Only local sandbox is allowed"
    schema = "test_finance_" + uuid4().hex
    administrative = create_engine(url)
    with administrative.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    sandbox_url = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
    database = Database(sandbox_url.render_as_string(hide_password=False))
    database.initialize()
    yield database, sandbox_url.render_as_string(hide_password=False)
    database.close()
    assert schema.startswith("test_finance_") and len(schema) == 45
    with administrative.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    administrative.dispose()


def test_postgres_migration_matches_schema_and_atomic_rollback(postgres: Any) -> None:
    database, _ = postgres
    with database.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    service = FinanceService(database, 9001)
    with pytest.raises(DomainError):
        service.execute_batch(
            [
                {"operation": "create_area", "payload": {"name": "Fictício"}},
                {"operation": "create_transaction", "payload": {"amount_minor": -1}},
            ],
            idempotency_key="invalid",
        )
    assert service.snapshot()["revision"] == 0
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxJob)) == 0


def test_postgres_first_workspace_and_idempotency_concurrent_engines(postgres: Any) -> None:
    database, url = postgres

    def run(_: int) -> dict[str, Any]:
        separate = Database(url)
        try:
            return FinanceService(separate, 9001).execute(
                "create_area", {"name": "Casa fictícia"}, idempotency_key="same"
            )
        finally:
            separate.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, range(12)))
    assert len({r["id"] for r in results}) == 1
    assert FinanceService(database, 9001).snapshot()["revision"] == 1


def test_postgres_job_skip_locked_and_event_uniqueness(postgres: Any) -> None:
    database, url = postgres
    store = DurableStore(database)
    store.enqueue("test", {}, dedupe_key="one")

    def run(index: int) -> dict[str, Any] | None:
        separate = Database(url)
        try:
            return DurableStore(separate).claim(f"worker{index}")
        finally:
            separate.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(run, range(6)))
    assert len([claim for claim in claims if claim]) == 1

    def receive(_: int) -> str:
        separate = Database(url)
        try:
            return DurableStore(separate).persist_inbound("sandbox", "42", 9001, {})["id"]
        finally:
            separate.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(receive, range(6)))
    assert len(set(ids)) == 1
