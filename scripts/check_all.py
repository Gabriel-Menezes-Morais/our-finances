"""Run deterministic checks; only the project's optional local Postgres is contacted."""

import argparse
import os
import subprocess
import sys

from dotenv import dotenv_values

from app.config import PROJECT_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-local", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.postgres_local:
        local = PROJECT_ROOT / "credentials" / "host-postgres.env"
        url = dotenv_values(local).get("DATABASE_URL")
        if not url or "@127.0.0.1:55439/our_finances" not in url:
            raise SystemExit("Credencial de teste PostgreSQL local ausente ou não reconhecida.")
        environment["OUR_FINANCES_TEST_POSTGRES_URL"] = url + (
            "&" if "?" in url else "?"
        ) + "connect_timeout=5"
    commands = [
        [sys.executable, "-B", "-m", "ruff", "check", "app", "scripts", "tests", "evals"],
        [
            sys.executable,
            "-B",
            "-m",
            "mypy",
            "--cache-dir=nul" if os.name == "nt" else "--cache-dir=/dev/null",
            "app",
            "scripts",
        ],
    ]
    tests = [sys.executable, "-B", "-m", "pytest", "-q"]
    if args.coverage:
        tests.extend(
            [
                "--cov=app",
                "--cov-report=term-missing:skip-covered",
                "--cov-report=json:data/sandbox/coverage.json",
            ]
        )
    commands.append(tests)
    for command in commands:
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=environment, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
    print("Checks concluídos. Nenhuma API de IA, áudio ou Telegram é chamada pela suíte.")


if __name__ == "__main__":
    main()
