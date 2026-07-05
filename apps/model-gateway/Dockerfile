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
RUN uv sync --frozen --no-install-workspace --no-dev --package rpim-model-gateway

COPY packages/shared packages/shared
COPY apps/model-gateway apps/model-gateway
RUN uv sync --frozen --no-dev --package rpim-model-gateway

EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "rpim_model_gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
