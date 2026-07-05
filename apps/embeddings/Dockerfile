# Build context = repo root. INSTALL_MODEL=true bakes the heavy ML extra
# (server); default false keeps CI builds light (fake backend only).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
ARG INSTALL_MODEL=false

COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
COPY apps/core-api/pyproject.toml apps/core-api/pyproject.toml
COPY apps/model-gateway/pyproject.toml apps/model-gateway/pyproject.toml
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
COPY apps/embeddings/pyproject.toml apps/embeddings/pyproject.toml
RUN if [ "$INSTALL_MODEL" = "true" ]; then \
	uv sync --frozen --no-install-workspace --no-dev --package rpim-embeddings --extra model; \
	else \
	uv sync --frozen --no-install-workspace --no-dev --package rpim-embeddings; \
	fi

COPY packages/shared packages/shared
COPY apps/embeddings apps/embeddings
RUN if [ "$INSTALL_MODEL" = "true" ]; then \
	uv sync --frozen --no-dev --package rpim-embeddings --extra model; \
	else \
	uv sync --frozen --no-dev --package rpim-embeddings; \
	fi

EXPOSE 8090
CMD ["uv", "run", "--no-sync", "uvicorn", "rpim_embeddings.main:app", "--host", "0.0.0.0", "--port", "8090"]
