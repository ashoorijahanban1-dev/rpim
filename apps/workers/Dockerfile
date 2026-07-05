# Build context = repo root (uv workspace layout).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
COPY apps/core-api/pyproject.toml apps/core-api/pyproject.toml
COPY apps/model-gateway/pyproject.toml apps/model-gateway/pyproject.toml
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
RUN uv sync --frozen --no-install-workspace --no-dev --package rpim-workers

COPY apps/workers apps/workers
RUN uv sync --frozen --no-dev --package rpim-workers

CMD ["uv", "run", "--no-sync", "celery", "-A", "rpim_workers.celery_app", "worker", "--loglevel=INFO", "--queues=rpim"]
