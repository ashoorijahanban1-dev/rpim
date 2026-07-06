"""
M8 acceptance tests — template renderer service, fake-mode core (US leg).

Blueprint §6.4 criteria:
  «۳ قالب × ۳ سایز، رندر < ۵ ثانیه، متن فارسی سالم»

Contract surface:
  GET /health
  POST /render   (guarded by X-Internal-Token)

RENDER_MODE=fake and INTERNAL_TOKEN are set at module level before any import
of rpim_renderer.main so the implementation reads the correct values at
request time (pattern from test_m2_embed.py / test_m7b_publish_telegram.py).
No literal secrets in this file — INTERNAL_TOKEN generated via secrets.token_hex
per run (CLAUDE.md rule 4).

All tests named test_m8_<criterion>.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets as _secrets
import socket

# ---------------------------------------------------------------------------
# Environment setup — MUST precede any import of rpim_renderer.main
# ---------------------------------------------------------------------------
os.environ.setdefault("RENDER_MODE", "fake")
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from rpim_renderer.main import app  # noqa: E402

_VALID_TOKEN = os.environ["INTERNAL_TOKEN"]
_RENDER_URL = "/render"

_PERSIAN_TITLE = "سلام دنیا ۱۲۳"
_PERSIAN_RTL = "می‌خواهیم ۵۰٪ رشد"  # contains ZWNJ (U+200C)

_TEMPLATES = ["announce", "quote", "product"]
_SIZES = ["square", "story", "wide"]

_SIZE_MAP = {
    "square": (1080, 1080),
    "story": (1080, 1920),
    "wide": (1280, 720),
}

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """TestClient for the renderer app."""
    with TestClient(app) as c:
        yield c


def _valid_body(
    template: str = "announce",
    size: str = "square",
    title: str = _PERSIAN_TITLE,
    body: str = "",
    cta: str = "",
    tenant_id: str = "tenant-test",
) -> dict:
    return {
        "template": template,
        "size": size,
        "tenant_id": tenant_id,
        "text": {"title": title, "body": body, "cta": cta},
    }


def _post_render(client: TestClient, payload: dict, *, token: str = _VALID_TOKEN) -> object:
    return client.post(
        _RENDER_URL,
        json=payload,
        headers={"X-Internal-Token": token},
    )


# ---------------------------------------------------------------------------
# 1. Health
# ---------------------------------------------------------------------------


def test_m8_health_returns_200(client: TestClient) -> None:
    """GET /health → 200."""
    resp = client.get("/health")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"


def test_m8_health_service_and_leg(client: TestClient) -> None:
    """GET /health → JSON with service=='renderer' and leg=='us'."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("service") == "renderer", f"service mismatch: {body}"
    assert body.get("leg") == "us", f"leg mismatch: {body}"
    assert body.get("status") == "ok", f"status mismatch: {body}"


# ---------------------------------------------------------------------------
# 2. Authentication guard on POST /render
# ---------------------------------------------------------------------------


def test_m8_render_missing_token_returns_401(client: TestClient) -> None:
    """POST /render without X-Internal-Token → 401 (mirrors _require_internal in gateway)."""
    resp = client.post(_RENDER_URL, json=_valid_body())
    assert resp.status_code == 401, (
        f"expected 401 for missing token, got {resp.status_code}: {resp.text}"
    )


def test_m8_render_wrong_token_returns_401(client: TestClient) -> None:
    """POST /render with an incorrect X-Internal-Token → 401."""
    resp = client.post(
        _RENDER_URL,
        json=_valid_body(),
        headers={"X-Internal-Token": "definitely-wrong-secret"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for wrong token, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 3. Request body validation → 422
# ---------------------------------------------------------------------------


def test_m8_render_unknown_template_returns_422(client: TestClient) -> None:
    """Unknown template value → 422 Unprocessable Entity."""
    payload = _valid_body(template="banner")
    resp = _post_render(client, payload)
    assert resp.status_code == 422, (
        f"expected 422 for unknown template, got {resp.status_code}: {resp.text}"
    )


def test_m8_render_unknown_size_returns_422(client: TestClient) -> None:
    """Unknown size value → 422 Unprocessable Entity."""
    payload = _valid_body(size="portrait")
    resp = _post_render(client, payload)
    assert resp.status_code == 422, (
        f"expected 422 for unknown size, got {resp.status_code}: {resp.text}"
    )


def test_m8_render_empty_title_returns_422(client: TestClient) -> None:
    """Empty/whitespace title → 422 (title is required and min_length 1)."""
    payload = _valid_body(title="")
    resp = _post_render(client, payload)
    assert resp.status_code == 422, (
        f"expected 422 for empty title, got {resp.status_code}: {resp.text}"
    )


def test_m8_render_whitespace_title_returns_422(client: TestClient) -> None:
    """Whitespace-only title → 422."""
    payload = _valid_body(title="   ")
    resp = _post_render(client, payload)
    assert resp.status_code == 422, (
        f"expected 422 for whitespace title, got {resp.status_code}: {resp.text}"
    )


def test_m8_render_missing_tenant_id_returns_422(client: TestClient) -> None:
    """Missing tenant_id → 422."""
    payload = {
        "template": "announce",
        "size": "square",
        "text": {"title": _PERSIAN_TITLE},
    }
    resp = _post_render(client, payload)
    assert resp.status_code == 422, (
        f"expected 422 for missing tenant_id, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 4. Successful render — all 9 combinations (3 templates × 3 sizes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", _TEMPLATES)
@pytest.mark.parametrize("size", _SIZES)
def test_m8_render_all_9_combinations(client: TestClient, template: str, size: str) -> None:
    """RENDER_MODE=fake → 200 JSON with correct shape for all 9 template×size combos."""
    payload = _valid_body(template=template, size=size, title=_PERSIAN_TITLE)
    resp = _post_render(client, payload)
    assert resp.status_code == 200, (
        f"expected 200 for {template}/{size}, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "image_b64" in body, f"'image_b64' missing: {body}"
    assert "meta" in body, f"'meta' missing: {body}"
    meta = body["meta"]
    assert meta.get("template") == template, f"meta.template mismatch: {meta}"
    assert meta.get("size") == size, f"meta.size mismatch: {meta}"
    assert meta.get("render_mode") == "fake", f"meta.render_mode mismatch: {meta}"
    assert meta.get("tenant_id") == "tenant-test", f"meta.tenant_id mismatch: {meta}"
    assert "text_sha256" in meta, f"'text_sha256' missing from meta: {meta}"
    assert "width" in meta, f"'width' missing from meta: {meta}"
    assert "height" in meta, f"'height' missing from meta: {meta}"


@pytest.mark.parametrize("size,expected_wh", list(_SIZE_MAP.items()))
def test_m8_render_size_map_pinned(
    client: TestClient, size: str, expected_wh: tuple[int, int]
) -> None:
    """Size → width×height mapping must match the pinned values."""
    expected_w, expected_h = expected_wh
    payload = _valid_body(size=size)
    resp = _post_render(client, payload)
    assert resp.status_code == 200, resp.text
    meta = resp.json()["meta"]
    assert meta.get("width") == expected_w, (
        f"{size}: expected width={expected_w}, got {meta.get('width')}"
    )
    assert meta.get("height") == expected_h, (
        f"{size}: expected height={expected_h}, got {meta.get('height')}"
    )


def test_m8_render_image_is_png(client: TestClient) -> None:
    """Decoded image_b64 must start with PNG magic bytes."""
    payload = _valid_body()
    resp = _post_render(client, payload)
    assert resp.status_code == 200, resp.text
    raw = base64.b64decode(resp.json()["image_b64"])
    assert raw[:8] == _PNG_MAGIC, (
        f"expected PNG magic {_PNG_MAGIC!r}, got {raw[:8]!r}"
    )


def test_m8_render_idempotent(client: TestClient) -> None:
    """Same request twice → byte-identical image_b64 and same text_sha256 (resumability)."""
    payload = _valid_body(title=_PERSIAN_TITLE, body="متن", cta="بیشتر")
    resp1 = _post_render(client, payload)
    resp2 = _post_render(client, payload)
    assert resp1.status_code == 200, resp1.text
    assert resp2.status_code == 200, resp2.text
    body1, body2 = resp1.json(), resp2.json()
    assert body1["image_b64"] == body2["image_b64"], "image_b64 is not idempotent"
    assert body1["meta"]["text_sha256"] == body2["meta"]["text_sha256"], (
        "text_sha256 is not idempotent"
    )


def test_m8_render_text_sha256_formula(client: TestClient) -> None:
    """text_sha256 == sha256(f'{title}\\n{body}\\n{cta}'.encode()).hexdigest()."""
    title, body, cta = _PERSIAN_TITLE, "محتوا", "اکنون"
    expected = hashlib.sha256(f"{title}\n{body}\n{cta}".encode()).hexdigest()
    payload = _valid_body(title=title, body=body, cta=cta)
    resp = _post_render(client, payload)
    assert resp.status_code == 200, resp.text
    got = resp.json()["meta"]["text_sha256"]
    assert got == expected, f"text_sha256 mismatch: expected {expected!r}, got {got!r}"


# ---------------------------------------------------------------------------
# 5. Pure template function — html_for offline proxy for «متن فارسی سالم»
# ---------------------------------------------------------------------------


def test_m8_html_for_rtl_and_lang() -> None:
    """html_for returns full HTML containing dir=\"rtl\" and lang=\"fa\"."""
    from rpim_renderer.templates import html_for

    html = html_for("announce", "square", {"title": _PERSIAN_TITLE})
    assert 'dir="rtl"' in html, f"dir=\"rtl\" not found in html:\n{html[:500]}"
    assert 'lang="fa"' in html, f"lang=\"fa\" not found in html:\n{html[:500]}"


def test_m8_html_for_persian_text_verbatim() -> None:
    """html_for includes the title string VERBATIM, including ZWNJ characters."""
    from rpim_renderer.templates import html_for

    html = html_for("announce", "square", {"title": _PERSIAN_RTL})
    assert _PERSIAN_RTL in html, (
        f"Persian title with ZWNJ not found verbatim in html:\n{html[:500]}"
    )


def test_m8_html_for_vazirmatn_font() -> None:
    """html_for output must reference 'Vazirmatn' in a font-family declaration."""
    from rpim_renderer.templates import html_for

    html = html_for("quote", "story", {"title": _PERSIAN_TITLE})
    assert "Vazirmatn" in html, f"'Vazirmatn' font not found in html:\n{html[:500]}"


@pytest.mark.parametrize("size,expected_wh", list(_SIZE_MAP.items()))
def test_m8_html_for_pixel_dimensions(size: str, expected_wh: tuple[int, int]) -> None:
    """html_for embeds both pixel dimensions of the chosen size."""
    from rpim_renderer.templates import html_for

    w, h = expected_wh
    html = html_for("product", size, {"title": _PERSIAN_TITLE})
    assert f"{w}px" in html, f"{w}px not found in html for size={size}:\n{html[:500]}"
    assert f"{h}px" in html, f"{h}px not found in html for size={size}:\n{html[:500]}"


def test_m8_html_for_unknown_template_raises_value_error() -> None:
    """html_for raises ValueError for an unknown template name."""
    from rpim_renderer.templates import html_for

    with pytest.raises(ValueError):
        html_for("banner", "square", {"title": _PERSIAN_TITLE})


def test_m8_html_for_unknown_size_raises_value_error() -> None:
    """html_for raises ValueError for an unknown size name."""
    from rpim_renderer.templates import html_for

    with pytest.raises(ValueError):
        html_for("announce", "portrait", {"title": _PERSIAN_TITLE})


# ---------------------------------------------------------------------------
# 6. No network in fake mode
# ---------------------------------------------------------------------------


def test_m8_no_network_in_fake_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake renderer must be pure in-process — no socket.connect calls allowed."""
    original_connect = socket.socket.connect

    def _no_connect(self: socket.socket, address: object) -> None:
        raise AssertionError(
            f"Network access forbidden in fake mode — attempted connect to {address!r}"
        )

    monkeypatch.setattr(socket.socket, "connect", _no_connect)

    payload = _valid_body()
    resp = _post_render(client, payload)
    assert resp.status_code == 200, (
        f"render failed unexpectedly (or triggered network): {resp.status_code}: {resp.text}"
    )

    monkeypatch.setattr(socket.socket, "connect", original_connect)
