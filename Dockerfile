FROM ghcr.io/astral-sh/uv:0.10.3 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
RUN useradd --uid 10001 --create-home finances && mkdir -p data exports && chown -R finances:finances /app
USER finances
ENV PATH="/app/.venv/bin:$PATH" PORT=8000
EXPOSE 8000
CMD ["python", "-m", "scripts.container_start"]
