# Build context = repo root (uv workspace needs packages/shared).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
COPY apps/core-api/pyproject.toml apps/core-api/pyproject.toml
COPY apps/model-gateway/pyproject.toml apps/model-gateway/pyproject.toml
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
RUN uv sync --frozen --no-install-workspace --no-dev --package rpim-core-api

COPY packages/shared packages/shared
COPY apps/core-api apps/core-api
RUN uv sync --frozen --no-dev --package rpim-core-api

EXPOSE 8000
# Migrations run at start (Alembic-only schema rule); then the API serves.
CMD ["sh", "-c", "cd apps/core-api && uv run --no-sync alembic upgrade head && exec uv run --no-sync uvicorn rpim_core_api.main:app --host 0.0.0.0 --port 8000"]
