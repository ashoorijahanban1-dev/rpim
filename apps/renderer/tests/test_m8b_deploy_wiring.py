"""
M8 slice-B deploy-wiring tests — offline, always run.

Checks that the infrastructure artefacts needed to run the live-rendering
renderer service exist and are correctly structured.

Files checked:
  apps/renderer/Dockerfile
  docker-compose.us.yml         (renderer service)
  .env.us.example               (RENDER_MODE, RENDERER_PORT names)
  apps/renderer/pyproject.toml  (optional dep group "live" with playwright)

Tests named test_m8b_<criterion>.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

_REPO_ROOT = Path("/home/user/beewaz")
_RENDERER_DOCKERFILE = _REPO_ROOT / "apps" / "renderer" / "Dockerfile"
_COMPOSE_US = _REPO_ROOT / "docker-compose.us.yml"
_ENV_US_EXAMPLE = _REPO_ROOT / ".env.us.example"
_RENDERER_PYPROJECT = _REPO_ROOT / "apps" / "renderer" / "pyproject.toml"


# ---------------------------------------------------------------------------
# 1. apps/renderer/Dockerfile
# ---------------------------------------------------------------------------


def test_m8b_dockerfile_exists() -> None:
    """apps/renderer/Dockerfile must exist."""
    assert _RENDERER_DOCKERFILE.exists(), (
        f"Dockerfile not found at {_RENDERER_DOCKERFILE}"
    )


def test_m8b_dockerfile_contains_playwright() -> None:
    """Dockerfile must reference 'playwright' (install step)."""
    assert _RENDERER_DOCKERFILE.exists(), (
        f"Dockerfile not found at {_RENDERER_DOCKERFILE}"
    )
    text = _RENDERER_DOCKERFILE.read_text()
    assert "playwright" in text.lower(), (
        "Dockerfile does not mention 'playwright' — playwright install step missing"
    )


def test_m8b_dockerfile_contains_chromium() -> None:
    """Dockerfile must reference 'chromium' (browser install step)."""
    assert _RENDERER_DOCKERFILE.exists(), (
        f"Dockerfile not found at {_RENDERER_DOCKERFILE}"
    )
    text = _RENDERER_DOCKERFILE.read_text()
    assert "chromium" in text.lower(), (
        "Dockerfile does not mention 'chromium' — browser install step missing"
    )


def test_m8b_dockerfile_has_healthcheck() -> None:
    """Dockerfile must contain a HEALTHCHECK instruction."""
    assert _RENDERER_DOCKERFILE.exists(), (
        f"Dockerfile not found at {_RENDERER_DOCKERFILE}"
    )
    text = _RENDERER_DOCKERFILE.read_text()
    assert "HEALTHCHECK" in text, (
        "Dockerfile missing HEALTHCHECK instruction"
    )


def test_m8b_dockerfile_cmd_runs_uvicorn_rpim_renderer() -> None:
    """Dockerfile CMD must run uvicorn with rpim_renderer.main:app."""
    assert _RENDERER_DOCKERFILE.exists(), (
        f"Dockerfile not found at {_RENDERER_DOCKERFILE}"
    )
    text = _RENDERER_DOCKERFILE.read_text()
    assert "uvicorn" in text, (
        "Dockerfile CMD does not reference uvicorn"
    )
    assert "rpim_renderer.main:app" in text, (
        "Dockerfile CMD does not reference rpim_renderer.main:app"
    )


# ---------------------------------------------------------------------------
# 2. docker-compose.us.yml — renderer service
# ---------------------------------------------------------------------------


def _load_renderer_service() -> dict:
    """Parse docker-compose.us.yml and return the renderer service dict (may be empty)."""
    compose = yaml.safe_load(_COMPOSE_US.read_text())
    return compose.get("services", {}).get("renderer", {})


def test_m8b_compose_us_has_renderer_service() -> None:
    """docker-compose.us.yml must define a 'renderer' service."""
    compose = yaml.safe_load(_COMPOSE_US.read_text())
    services = compose.get("services", {})
    assert "renderer" in services, (
        f"'renderer' service not found in docker-compose.us.yml; "
        f"present services: {sorted(services)}"
    )


def test_m8b_compose_renderer_build_dockerfile() -> None:
    """renderer service build.dockerfile must point to apps/renderer/Dockerfile."""
    renderer = _load_renderer_service()
    assert renderer, "'renderer' service not found in docker-compose.us.yml"
    build = renderer.get("build", {})
    dockerfile = build.get("dockerfile", "")
    assert "apps/renderer/Dockerfile" in dockerfile, (
        f"renderer build.dockerfile must include 'apps/renderer/Dockerfile', "
        f"got: {dockerfile!r}"
    )


def test_m8b_compose_renderer_build_context_is_repo_root() -> None:
    """renderer service build.context must be '.' (repo root — workspace build context)."""
    renderer = _load_renderer_service()
    assert renderer, "'renderer' service not found in docker-compose.us.yml"
    build = renderer.get("build", {})
    context = build.get("context", "")
    assert context == ".", (
        f"renderer build.context must be '.', got: {context!r}"
    )


def test_m8b_compose_renderer_env_has_render_mode() -> None:
    """renderer service environment must include RENDER_MODE."""
    renderer = _load_renderer_service()
    assert renderer, "'renderer' service not found in docker-compose.us.yml"
    env = renderer.get("environment", {})
    if isinstance(env, dict):
        has_key = "RENDER_MODE" in env
    else:
        has_key = any(str(e).startswith("RENDER_MODE") for e in env)
    assert has_key, (
        f"renderer service environment must include RENDER_MODE; got: {env}"
    )


def test_m8b_compose_renderer_env_has_internal_token() -> None:
    """renderer service environment must include INTERNAL_TOKEN interpolation."""
    renderer = _load_renderer_service()
    assert renderer, "'renderer' service not found in docker-compose.us.yml"
    env = renderer.get("environment", {})
    if isinstance(env, dict):
        has_key = "INTERNAL_TOKEN" in env
    else:
        has_key = any(str(e).startswith("INTERNAL_TOKEN") for e in env)
    assert has_key, (
        f"renderer service environment must include INTERNAL_TOKEN; got: {env}"
    )


def test_m8b_compose_renderer_has_healthcheck() -> None:
    """renderer service must define a healthcheck."""
    renderer = _load_renderer_service()
    assert renderer, "'renderer' service not found in docker-compose.us.yml"
    assert "healthcheck" in renderer, (
        "renderer service missing 'healthcheck' key in docker-compose.us.yml"
    )


def test_m8b_compose_renderer_no_public_host_port() -> None:
    """renderer service must NOT expose a public host port.
    Ports list must be absent, empty, or every entry must start with
    '127.0.0.1' or use a compose interpolation default of '127.0.0.1'.
    """
    renderer = _load_renderer_service()
    assert renderer, "'renderer' service not found in docker-compose.us.yml"
    ports = renderer.get("ports", [])
    if not ports:
        return  # no ports at all — passes the constraint
    for entry in ports:
        entry_str = str(entry)
        is_loopback = entry_str.startswith("127.0.0.1")
        is_interpolated = "${" in entry_str  # compose interpolation guard
        assert is_loopback or is_interpolated, (
            f"renderer port {entry_str!r} must be loopback-guarded "
            "(start with 127.0.0.1 or use compose ${...} interpolation)"
        )


# ---------------------------------------------------------------------------
# 3. .env.us.example — required variable names
# ---------------------------------------------------------------------------


def test_m8b_env_example_has_render_mode() -> None:
    """.env.us.example must declare RENDER_MODE (name only; value may be empty)."""
    text = _ENV_US_EXAMPLE.read_text()
    found = any(
        line.startswith("RENDER_MODE") for line in text.splitlines()
        if not line.startswith("#")
    )
    assert found, (
        "RENDER_MODE= line not found in .env.us.example"
    )


def test_m8b_env_example_has_renderer_port() -> None:
    """.env.us.example must declare RENDERER_PORT (name only; value may be empty)."""
    text = _ENV_US_EXAMPLE.read_text()
    found = any(
        line.startswith("RENDERER_PORT") for line in text.splitlines()
        if not line.startswith("#")
    )
    assert found, (
        "RENDERER_PORT= line not found in .env.us.example"
    )


# ---------------------------------------------------------------------------
# 4. apps/renderer/pyproject.toml — optional dependency group "live"
# ---------------------------------------------------------------------------


def test_m8b_pyproject_live_group_contains_playwright() -> None:
    """pyproject.toml must declare an optional dep group 'live' containing 'playwright'.
    Accepts both [dependency-groups.live] (PEP 735 / uv) and
    [project.optional-dependencies.live] (PEP 508).
    """
    with _RENDERER_PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)

    # PEP 735 / uv style: [dependency-groups]
    dep_groups = data.get("dependency-groups", {})
    # Classic PEP 508 style: [project.optional-dependencies]
    opt_deps = data.get("project", {}).get("optional-dependencies", {})

    live_deps: list = list(dep_groups.get("live", [])) or list(opt_deps.get("live", []))

    assert live_deps, (
        "No 'live' optional dependency group found in apps/renderer/pyproject.toml. "
        "Expected [dependency-groups.live] or [project.optional-dependencies.live]."
    )

    has_playwright = any("playwright" in str(dep).lower() for dep in live_deps)
    assert has_playwright, (
        f"'playwright' not listed in the 'live' dependency group; got: {live_deps}"
    )
