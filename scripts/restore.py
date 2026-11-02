"""Restore into a new sandbox database; restored jobs cannot publish or send."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.config import PROJECT_ROOT
from app.db import Database
from app.models import Base
from scripts.backup import local_key, read_backup


def restore_backup(source: Path, database: Database, key: bytes) -> dict[str, int]:
    manifest = read_backup(source, key)
    tables: dict[str, list[dict[str, Any]]] = deepcopy(manifest["tables"])
    expected = {table.name for table in Base.metadata.sorted_tables}
    if set(tables) != expected:
        raise ValueError("Esquema do backup incompatível; use a versão correspondente.")
    database.initialize()
    counts: dict[str, int] = {}
    with database.engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if connection.scalar(select(func.count()).select_from(table)):
                raise ValueError("Restauração exige um banco vazio e isolado.")
        for table in Base.metadata.sorted_tables:
            rows = tables[table.name]
            permitted = set(table.columns.keys())
            if any(set(row) - permitted for row in rows):
                raise ValueError("Coluna de backup não permitida.")
            for row in rows:
                if table.name == "outbox_jobs":
                    row.update(
                        status="uncertain",
                        lease_owner=None,
                        lease_until=None,
                        last_error="restored_sandbox_no_external_delivery",
                    )
                elif table.name == "inbound_events":
                    row["status"] = "processed"
                elif table.name == "pending_actions":
                    row["status"] = "cancelled"
                elif table.name == "workspaces":
                    row["flags"] = {
                        **row.get("flags", {}),
                        **{flag: True for flag in ("ai", "audio", "excel", "sheets", "schedules")},
                    }
            if rows:
                connection.execute(table.insert(), rows)
            counts[table.name] = len(rows)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Restaura somente em novo SQLite de sandbox.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if not args.name.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Nome de sandbox inválido.")
    directory = PROJECT_ROOT / "data" / "restore_sandbox"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (args.name + ".sqlite3")
    if target.exists() or target.is_symlink():
        raise SystemExit("Destino já existe; nenhuma sobrescrita realizada.")
    database = Database("sqlite+pysqlite:///" + target.as_posix())
    try:
        counts = restore_backup(args.source, database, local_key())
        print(f"Sandbox restaurado: {sum(counts.values())} linhas. Jobs externos suspensos.")
    except Exception:
        print("Restauração não concluída. Destino original preservado; detalhes privados ocultos.")
        raise SystemExit(1) from None
    finally:
        database.close()


if __name__ == "__main__":
    main()
