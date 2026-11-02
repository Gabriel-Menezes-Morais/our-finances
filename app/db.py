"""Explicit database lifecycle; importing this module never opens a connection."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base


class Database:
    def __init__(self, url: str) -> None:
        options: dict[str, object] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url or url == "sqlite://":
                options["poolclass"] = StaticPool
        else:
            options.update(pool_size=3, max_overflow=2)
        self.engine = create_engine(url, **options)
        self.lock = RLock()
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", self._sqlite_foreign_keys)

    @staticmethod
    def _sqlite_foreign_keys(connection: object, _: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    def initialize(self) -> None:
        from alembic import command
        from alembic.autogenerate import compare_metadata
        from alembic.config import Config
        from alembic.migration import MigrationContext

        root = Path(__file__).resolve().parents[1]
        configuration = Config(str(root / "alembic.ini"))
        configuration.set_main_option("script_location", str(root / "migrations"))
        with self.lock, self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(109617, 0)"))
            configuration.attributes["connection"] = connection
            tables = inspect(connection).get_table_names()
            if "workspaces" in tables and "alembic_version" not in tables:
                # Safely recognize only the exact schema created by an earlier
                # local build. Unknown unversioned schemas require manual review.
                differences = compare_metadata(
                    MigrationContext.configure(connection), Base.metadata
                )
                if differences:
                    raise RuntimeError(
                        "Banco sem versão tem esquema divergente; revise a migração."
                    )
                command.stamp(configuration, "head")
            command.upgrade(configuration, "head")

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.lock, self.sessions.begin() as session:
            yield session

    def health(self) -> bool:
        with self.session() as session:
            return bool(session.scalar(text("SELECT 1")) == 1)

    def close(self) -> None:
        self.engine.dispose()
