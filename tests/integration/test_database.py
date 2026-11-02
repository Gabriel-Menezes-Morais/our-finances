from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from app.db import Database
from app.domain import FinanceService
from app.models import Workspace


def test_empty_database_migrations_and_rollback(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    config = Config("alembic.ini")
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    assert {"transactions", "allocations", "audit_events", "outbox_jobs"} <= set(
        inspect(database.engine).get_table_names()
    )
    with pytest.raises(RuntimeError), database.session() as session:
        session.add(Workspace(owner_id=123))
        session.flush()
        raise RuntimeError("rollback")
    with database.session() as session:
        assert session.scalar(select(Workspace)) is None
    assert database.health()
    assert FinanceService(database, 123).snapshot()["revision"] == 0


def test_database_survives_new_engine(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}"
    first = Database(url)
    first.initialize()
    FinanceService(first, 123).execute("create_area", {"name": "Casa"}, idempotency_key="1")
    first.close()
    second = Database(url)
    assert FinanceService(second, 123).snapshot()["areas"][0]["name"] == "Casa"
