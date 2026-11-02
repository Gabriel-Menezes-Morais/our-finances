"""Apply versioned migrations without putting database credentials in commands or logs."""

from alembic import command
from alembic.config import Config

from app.config import PROJECT_ROOT, Settings
from app.db import Database


def migrate(settings: Settings) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        database.close()


def main() -> None:
    try:
        (PROJECT_ROOT / "data").mkdir(exist_ok=True)
        migrate(Settings())
        print("Migrações aplicadas. URL e credenciais ocultas.")
    except Exception:
        print("Migração não concluída; banco preservado. Confira o ambiente e a versão do esquema.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
