"""Authenticated encrypted portable database backup; no cloud or provider calls."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.config import PROJECT_ROOT, Settings
from app.db import Database
from app.models import Base

MAX_BACKUP_BYTES = 100 * 1024 * 1024


def local_key(root: Path = PROJECT_ROOT) -> bytes:
    location = root / "credentials" / "backup.key"
    location.parent.mkdir(exist_ok=True)
    if location.is_symlink():
        raise ValueError("Chave de backup não pode ser um link simbólico.")
    if not location.exists():
        # Publish a fully written key atomically. A losing process reads the
        # winner's complete key rather than overwriting or observing a partial file.
        with tempfile.NamedTemporaryFile(dir=location.parent, delete=False) as temporary:
            temporary.write(Fernet.generate_key())
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            try:
                os.link(temporary_path, location)
            except FileExistsError:
                pass
        finally:
            temporary_path.unlink()
    key = location.read_bytes()
    Fernet(key)
    return key


def create_backup(database: Database, destination: Path, key: bytes) -> Path:
    data: dict[str, list[dict[str, Any]]] = {}
    with database.engine.connect() as connection:
        if database.engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        with connection.begin():
            if database.engine.dialect.name == "sqlite":
                # sqlite3 legacy mode does not BEGIN on SELECT; explicitly obtain
                # one read snapshot across all tables while other writers may run.
                connection.exec_driver_sql("BEGIN")
            for table in Base.metadata.sorted_tables:
                rows = connection.execute(select(table)).mappings().all()
                data[table.name] = [dict(row) for row in rows]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    manifest = {
        "format": "our-finances-backup-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "tables": data,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Backup de destino já existe; escolha outro arquivo.")
    encrypted = Fernet(key).encrypt(
        gzip.compress(json.dumps(manifest, ensure_ascii=False).encode())
    )
    with destination.open("xb") as output:
        output.write(encrypted)
    return destination


def read_backup(source: Path, key: bytes) -> dict[str, Any]:
    if source.stat().st_size > MAX_BACKUP_BYTES:
        raise ValueError("Backup excede o limite local.")
    try:
        compressed = Fernet(key).decrypt(source.read_bytes())
    except InvalidToken:
        raise ValueError("Chave inválida ou backup alterado.") from None
    import io

    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
        raw = archive.read(MAX_BACKUP_BYTES + 1)
    if len(raw) > MAX_BACKUP_BYTES:
        raise ValueError("Conteúdo descomprimido excede o limite local.")
    manifest: dict[str, Any] = json.loads(raw)
    if manifest.get("format") != "our-finances-backup-v1":
        raise ValueError("Formato de backup desconhecido.")
    payload = json.dumps(manifest["tables"], ensure_ascii=False, separators=(",", ":")).encode()
    if hashlib.sha256(payload).hexdigest() != manifest["sha256"]:
        raise ValueError("Integridade do backup não confere.")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup local cifrado, sem envio externo.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.output or PROJECT_ROOT / "backups" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".ofbackup"
    )
    database = Database(Settings().database_url.get_secret_value())
    try:
        create_backup(database, destination, local_key())
        print("Backup local cifrado concluído. Guarde a chave separadamente antes de produção.")
    except Exception:
        print("Backup não concluído. Verifique banco, destino e chave; dados privados ocultos.")
        raise SystemExit(1) from None
    finally:
        database.close()


if __name__ == "__main__":
    main()
