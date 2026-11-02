"""Migrate before serving the PaaS web process; no shell interpolation."""

import logging

import uvicorn

from app.config import Settings
from app.main import create_app
from scripts.migrate import migrate


def main() -> None:
    logging.disable(logging.CRITICAL)
    settings = Settings()
    try:
        migrate(settings)
        uvicorn.run(
            create_app(settings),
            host="0.0.0.0",
            port=settings.port,
            access_log=False,
            log_level="critical",
        )
    except Exception:
        print("Inicialização interrompida. Confira configuração/migrações; segredos ocultos.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
