# Build context = repo root (uv workspace needs packages/shared).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
COPY apps/renderer/pyproject.toml apps/renderer/pyproject.toml
RUN uv sync --frozen --no-install-workspace --no-dev --package rpim-renderer --extra live

COPY packages/shared packages/shared
COPY apps/renderer apps/renderer
RUN uv sync --frozen --no-dev --package rpim-renderer --extra live

# Chromium + OS deps for headless rendering with Persian glyphs (playwright
# pulls the browser; fonts-vazirmatn supplies the brand font stack).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-vazirmatn \
    && rm -rf /var/lib/apt/lists/* \
    && uv run --no-sync playwright install --with-deps chromium

ENV RENDER_MODE=fake
EXPOSE 8091
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=15s \
    CMD ["python", "-c", "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8091/health',timeout=3).status==200 else 1)"]
CMD ["uv", "run", "--no-sync", "uvicorn", "rpim_renderer.main:app", "--host", "0.0.0.0", "--port", "8091"]
