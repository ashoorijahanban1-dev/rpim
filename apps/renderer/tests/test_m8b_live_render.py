"""
M8 slice-B failing tests — live Chromium rendering path.

Blueprint §6.4: «رندر < ۵ ثانیه، متن فارسی سالم»

Contract surface:
  rpim_renderer.chromium   – module: RenderUnavailable, screenshot_png
  POST /render             – RENDER_MODE=live path (200 or 503)

Tests named test_m8b_<criterion>.
No playwright import at module level; tests skip or fail gracefully per spec.
"""

from __future__ import annotations

import base64
import importlib
import importlib.util
import os
import secrets as _secrets
import struct
import time

import pytest

# ---------------------------------------------------------------------------
# Environment setup — must precede rpim_renderer.main import.
# INTERNAL_TOKEN is generated once per session; RENDER_MODE stays unset here
# so individual tests control it via monkeypatch.setenv.
# ---------------------------------------------------------------------------
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))

_VALID_TOKEN: str = os.environ["INTERNAL_TOKEN"]
_RENDER_URL = "/render"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_CHROMIUM_BINARY = "/opt/pw-browsers/chromium"

# ---------------------------------------------------------------------------
# Availability probes — evaluated once at collection time.
# ---------------------------------------------------------------------------

_PLAYWRIGHT_AVAILABLE: bool = importlib.util.find_spec("playwright") is not None
_CHROMIUM_BINARY_EXISTS: bool = os.path.exists(_CHROMIUM_BINARY)

_SKIP_LIVE = pytest.mark.skipif(
    not _PLAYWRIGHT_AVAILABLE or not _CHROMIUM_BINARY_EXISTS,
    reason=(
        "playwright not installed or chromium binary not found at "
        f"{_CHROMIUM_BINARY}"
    ),
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _valid_body(
    template: str = "announce",
    size: str = "square",
    title: str = "عنوان تست",
    body: str = "",
    cta: str = "",
    tenant_id: str = "tenant-live-test",
) -> dict:
    return {
        "template": template,
        "size": size,
        "tenant_id": tenant_id,
        "text": {"title": title, "body": body, "cta": cta},
    }


# ---------------------------------------------------------------------------
# 1. Module-structure tests — always run (no playwright needed)
# ---------------------------------------------------------------------------


def test_m8b_chromium_module_importable() -> None:
    """rpim_renderer.chromium must exist and be importable."""
    import rpim_renderer.chromium  # noqa: F401 — fails if module absent


def test_m8b_screenshot_png_is_callable() -> None:
    """rpim_renderer.chromium must export a callable named screenshot_png."""
    chromium = importlib.import_module("rpim_renderer.chromium")
    fn = getattr(chromium, "screenshot_png", None)
    assert callable(fn), (
        "screenshot_png not found or not callable in rpim_renderer.chromium"
    )


def test_m8b_render_unavailable_is_exception_class() -> None:
    """rpim_renderer.chromium must export RenderUnavailable(Exception)."""
    chromium = importlib.import_module("rpim_renderer.chromium")
    cls = getattr(chromium, "RenderUnavailable", None)
    assert cls is not None, "RenderUnavailable not found in rpim_renderer.chromium"
    assert issubclass(cls, Exception), (
        f"RenderUnavailable must subclass Exception, got {cls!r}"
    )


# ---------------------------------------------------------------------------
# 2. main.py live-path tests — always run, monkeypatched (no browser needed)
# ---------------------------------------------------------------------------


def test_m8b_live_503_when_chromium_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RENDER_MODE=live + screenshot_png raises RenderUnavailable → 503.
    The 503 detail must name 'playwright' or 'chromium' (no paths/secrets).
    """
    monkeypatch.setenv("RENDER_MODE", "live")

    import rpim_renderer.chromium as _chromium_mod
    from rpim_renderer.chromium import RenderUnavailable

    def _raise(html: str, width: int, height: int) -> bytes:
        raise RenderUnavailable("chromium unavailable in test")

    monkeypatch.setattr(_chromium_mod, "screenshot_png", _raise)

    from fastapi.testclient import TestClient

    from rpim_renderer.main import app

    with TestClient(app) as client:
        resp = client.post(
            _RENDER_URL,
            json=_valid_body(),
            headers={"X-Internal-Token": _VALID_TOKEN},
        )

    assert resp.status_code == 503, (
        f"expected 503 when chromium unavailable, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "playwright" in detail.lower() or "chromium" in detail.lower(), (
        f"503 detail must mention 'playwright' or 'chromium', got: {detail!r}"
    )


def test_m8b_live_200_with_monkeypatched_png(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RENDER_MODE=live + screenshot_png returns valid PNG bytes → 200.
    image_b64 must decode to exactly the bytes returned, render_mode=='live'.
    Never produces a fake/silent success — asserts the real live path is taken.
    """
    monkeypatch.setenv("RENDER_MODE", "live")

    import rpim_renderer.chromium as _chromium_mod
    from rpim_renderer.rendering import fake_png

    _tiny_png = fake_png(4, 4, "x")

    def _fake_screenshot(html: str, width: int, height: int) -> bytes:
        return _tiny_png

    monkeypatch.setattr(_chromium_mod, "screenshot_png", _fake_screenshot)

    from fastapi.testclient import TestClient

    from rpim_renderer.main import app

    with TestClient(app) as client:
        resp = client.post(
            _RENDER_URL,
            json=_valid_body(),
            headers={"X-Internal-Token": _VALID_TOKEN},
        )

    assert resp.status_code == 200, (
        f"expected 200 for live mode with monkeypatched screenshot, "
        f"got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert "image_b64" in data, f"'image_b64' missing in response: {data}"
    decoded = base64.b64decode(data["image_b64"])
    assert decoded == _tiny_png, (
        "image_b64 decoded bytes do not match the PNG bytes returned by screenshot_png"
    )
    meta = data.get("meta", {})
    assert meta.get("render_mode") == "live", (
        f"meta.render_mode must be 'live', got {meta.get('render_mode')!r}"
    )


# ---------------------------------------------------------------------------
# 3. Acceptance test — requires playwright + /opt/pw-browsers/chromium
# ---------------------------------------------------------------------------


@_SKIP_LIVE
def test_m8b_acceptance_real_chromium_renders_persian_text() -> None:
    """Blueprint §6.4: رندر < ۵ ثانیه، متن فارسی سالم.

    Requires playwright + /opt/pw-browsers/chromium.
    Renders a 1080×1080 frame with Persian text twice (different titles),
    verifies timing, PNG dimensions (IHDR), byte-length, and that the two
    frames differ (text actually painted on canvas).
    Determinism NOT required: antialiasing variance is allowed.
    """
    from rpim_renderer.chromium import screenshot_png
    from rpim_renderer.templates import html_for

    html_persian = html_for(
        "announce",
        "square",
        {
            "title": "سلام دنیا — تست ۱۲۳",
            "body": "متن بدنه با نیم‌فاصله می‌خواهیم",
            "cta": "همین حالا",
        },
    )
    html_latin = html_for(
        "announce",
        "square",
        {
            "title": "ABCD",
            "body": "متن بدنه با نیم‌فاصله می‌خواهیم",
            "cta": "همین حالا",
        },
    )

    start = time.monotonic()
    png_persian = screenshot_png(html_persian, 1080, 1080)
    duration = time.monotonic() - start

    assert duration < 5.0, (
        f"chromium render took {duration:.2f}s — must be < 5.0s (blueprint §6.4)"
    )

    png_latin = screenshot_png(html_latin, 1080, 1080)

    # PNG magic bytes
    assert png_persian[:8] == _PNG_MAGIC, (
        f"result does not start with PNG magic: {png_persian[:8]!r}"
    )

    # IHDR chunk: bytes 8..12 = length(4), 12..16 = "IHDR", 16..24 = width+height
    w, h = struct.unpack(">II", png_persian[16:24])
    assert w == 1080, f"PNG IHDR width expected 1080, got {w}"
    assert h == 1080, f"PNG IHDR height expected 1080, got {h}"

    # Not a blank or stub: a real 1080×1080 painted frame is much larger than 5 KB
    assert len(png_persian) > 5000, (
        f"PNG too small ({len(png_persian)} bytes) — likely a blank or stub render"
    )

    # «متن فارسی سالم» proxy: different title text → different pixel data
    assert png_persian != png_latin, (
        "PNG with 'سلام دنیا — تست ۱۲۳' and PNG with 'ABCD' are byte-identical "
        "— text was not painted onto the canvas"
    )
