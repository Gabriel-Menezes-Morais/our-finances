"""Generate only this project's local database credentials; never print secrets."""

import secrets
from pathlib import Path

from app.config import PROJECT_ROOT


def bootstrap(root: Path = PROJECT_ROOT) -> None:
    credentials = root / "credentials"
    credentials.mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    (root / "exports").mkdir(exist_ok=True)
    destination = credentials / "postgres.env"
    if destination.exists():
        print("Credenciais PostgreSQL locais já existem; nenhum valor substituído.")
        return
    password = secrets.token_urlsafe(32)
    destination.write_text(
        "POSTGRES_USER=our_finances\nPOSTGRES_DB=our_finances\nPOSTGRES_PASSWORD="
        + password
        + "\n",
        encoding="utf-8",
    )
    for name, host in (("app-postgres.env", "db:5432"), ("host-postgres.env", "127.0.0.1:55439")):
        (credentials / name).write_text(
            "DATABASE_URL=postgresql+psycopg://our_finances:"
            + password
            + "@"
            + host
            + "/our_finances\n",
            encoding="utf-8",
        )
    print("Credenciais locais geradas em credentials/ (ignorado pelo Git). Valores ocultos.")


if __name__ == "__main__":
    bootstrap()
