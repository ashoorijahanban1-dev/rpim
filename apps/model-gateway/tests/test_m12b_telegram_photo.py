"""
M12B acceptance tests — POST /publish/telegram-photo on the model-gateway (US leg).

This endpoint is the cross-leg photo seam: the iran-leg channels.send_photo
forwards multipart image jobs here instead of calling api.telegram.org directly
(CLAUDE.md rule 5: official APIs from the US leg only; browser automation
forbidden).

Auth contract: guarded by X-Internal-Token via the same _require_internal
helper used by /publish/telegram — inspected source returns 401 for
missing/wrong token (HTTPException status_code=401).

Endpoint accepts multipart form:
  chat_id : str (form field, required)
  caption : str (form field, may be empty)
  photo   : bytes (file field, required)

PUBLISH_MODE=fake: records into _tg._SENT with
  {"chat_id": ..., "caption": ..., "kind": "photo", "image_size": len(bytes)}.

Live path contract: send_telegram_photo(chat_id, caption, photo_png: bytes)
routes through module-level seam _post_multipart(url, data, files) — analogous
to send_telegram / _post_json pattern in M7B.

Module-level PUBLISH_MODE=fake and INTERNAL_TOKEN generation mirror
test_m7b_publish_telegram.py exactly (no literal secrets — rule 4).

All tests named test_m12b_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

# Set env vars BEFORE any import of the gateway app (pattern from test_m7b).
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
# PUBLISH_MODE=fake → /publish/telegram-photo uses in-process fake seam.
os.environ.setdefault("PUBLISH_MODE", "fake")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import rpim_model_gateway.telegram as _tg  # noqa: E402
from rpim_model_gateway.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_TOKEN: str = os.environ["INTERNAL_TOKEN"]
_PHOTO_URL = "/publish/telegram-photo"

# Minimal fake PNG bytes (PNG magic header + padding — enough to be non-empty).
_SAMPLE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gw_client():
    """TestClient for the model-gateway app (same pattern as test_m7b)."""
    with TestClient(app) as c:
        yield c


# ===========================================================================
# 1. Auth guard: missing X-Internal-Token → 401
# ===========================================================================


def test_m12b_telegram_photo_missing_token_returns_401(gw_client: TestClient):
    """POST /publish/telegram-photo without X-Internal-Token → 401.

    _require_internal raises HTTPException(status_code=401) for missing token
    (same guard as /publish/telegram).
    """
    resp = gw_client.post(
        _PHOTO_URL,
        data={"chat_id": "55", "caption": ""},
        files={"photo": ("image.png", _SAMPLE_PNG, "image/png")},
    )
    assert resp.status_code == 401, (
        f"expected 401 for missing X-Internal-Token, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 2. Auth guard: wrong X-Internal-Token → 401
# ===========================================================================


def test_m12b_telegram_photo_wrong_token_returns_401(gw_client: TestClient):
    """POST /publish/telegram-photo with incorrect X-Internal-Token → 401."""
    resp = gw_client.post(
        _PHOTO_URL,
        data={"chat_id": "55", "caption": ""},
        files={"photo": ("image.png", _SAMPLE_PNG, "image/png")},
        headers={"X-Internal-Token": "definitely-wrong-secret"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for wrong X-Internal-Token, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 3. Fake mode: valid multipart → 200 {"ok": true, ...}
# ===========================================================================


def test_m12b_telegram_photo_fake_mode_200_ok_true(
    gw_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """PUBLISH_MODE=fake, valid auth and multipart → 200 with {"ok": true}.

    Fake mode must not hit the Telegram network.
    """
    monkeypatch.setenv("PUBLISH_MODE", "fake")

    resp = gw_client.post(
        _PHOTO_URL,
        data={"chat_id": "55", "caption": "عکس تست"},
        files={"photo": ("image.png", _SAMPLE_PNG, "image/png")},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 for fake-mode telegram-photo send, "
        f"got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("ok") is True, (
        f'response must contain {{"ok": true}}, got: {body}'
    )


# ===========================================================================
# 4. Fake mode: _SENT entry has chat_id, caption, kind="photo", image_size
# ===========================================================================


def test_m12b_telegram_photo_fake_mode_records_in_sent_list(
    gw_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """PUBLISH_MODE=fake → entry appended to _tg._SENT with required fields.

    Entry must contain: chat_id, caption, "kind": "photo",
    and "image_size": len(photo_bytes).
    _SENT cleared before the call to isolate this assertion.
    """
    monkeypatch.setenv("PUBLISH_MODE", "fake")
    _tg._SENT.clear()

    chat_id = "42"
    caption = "عکس برند"
    photo_bytes = _SAMPLE_PNG

    gw_client.post(
        _PHOTO_URL,
        data={"chat_id": chat_id, "caption": caption},
        files={"photo": ("image.png", photo_bytes, "image/png")},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )

    assert len(_tg._SENT) == 1, (
        f"_SENT must have 1 entry after fake telegram-photo send, got: {_tg._SENT}"
    )
    entry = _tg._SENT[0]
    assert entry.get("chat_id") == chat_id, (
        f"_SENT entry chat_id must be {chat_id!r}, got {entry.get('chat_id')!r}"
    )
    assert entry.get("caption") == caption, (
        f"_SENT entry caption must be {caption!r}, got {entry.get('caption')!r}"
    )
    assert entry.get("kind") == "photo", (
        f"_SENT entry kind must be 'photo', got {entry.get('kind')!r}"
    )
    assert entry.get("image_size") == len(photo_bytes), (
        f"_SENT entry image_size must be {len(photo_bytes)}, "
        f"got {entry.get('image_size')!r}"
    )


# ===========================================================================
# 5. Live path: TELEGRAM_BOT_TOKEN unset → 503 naming the env var
# ===========================================================================


def test_m12b_telegram_photo_live_unset_token_503_names_var(
    gw_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """PUBLISH_MODE=live, TELEGRAM_BOT_TOKEN unset → 503; detail must contain
    'TELEGRAM_BOT_TOKEN' (var name only, never a token value).

    Constitution rule 4: credentials must never appear in error output.
    """
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    resp = gw_client.post(
        _PHOTO_URL,
        data={"chat_id": "55", "caption": ""},
        files={"photo": ("image.png", _SAMPLE_PNG, "image/png")},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 503, (
        f"expected 503 when TELEGRAM_BOT_TOKEN unset, "
        f"got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "TELEGRAM_BOT_TOKEN" in detail, (
        f"503 detail must name env var 'TELEGRAM_BOT_TOKEN', got: {detail!r}"
    )


# ===========================================================================
# 6. Live seam: _post_multipart receives sendPhoto URL, data dict, files dict
# ===========================================================================


def test_m12b_telegram_photo_live_seam_url_data_files(
    gw_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """PUBLISH_MODE=live, TELEGRAM_BOT_TOKEN set → _post_multipart called with
    url == f"https://api.telegram.org/bot{token}/sendPhoto",
    data dict containing chat_id and caption,
    files dict containing the photo bytes.

    Per-run token via monkeypatch.setenv (rule 4: no literal secrets in repo).
    raising=False on setattr because _post_multipart doesn't exist yet
    (the seam must be added to rpim_model_gateway.telegram as part of M12B).
    """
    token = _secrets.token_hex(16)
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    captured: dict = {}

    def fake_post_multipart(url: str, data: dict, files: dict) -> None:
        captured["url"] = url
        captured["data"] = dict(data)
        captured["files"] = dict(files)

    # raising=False: attribute doesn't exist yet; will be created by monkeypatch.
    monkeypatch.setattr(_tg, "_post_multipart", fake_post_multipart, raising=False)

    chat_id = "99"
    caption = "عکس لایو"
    photo_bytes = _SAMPLE_PNG

    resp = gw_client.post(
        _PHOTO_URL,
        data={"chat_id": chat_id, "caption": caption},
        files={"photo": ("image.png", photo_bytes, "image/png")},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 for live seam test, got {resp.status_code}: {resp.text}"
    )

    expected_url = f"https://api.telegram.org/bot{token}/sendPhoto"
    assert captured.get("url") == expected_url, (
        f"_post_multipart must be called with {expected_url!r}, "
        f"got {captured.get('url')!r}"
    )
    assert captured.get("data", {}).get("chat_id") == chat_id, (
        f"_post_multipart data must contain chat_id={chat_id!r}, "
        f"got data: {captured.get('data')!r}"
    )
    assert captured.get("data", {}).get("caption") == caption, (
        f"_post_multipart data must contain caption={caption!r}, "
        f"got data: {captured.get('data')!r}"
    )
    # files["photo"] must carry the photo bytes — accept raw bytes or a
    # (filename, bytes, mime) tuple; the exact shape is an implementation choice.
    files_captured = captured.get("files", {})
    photo_val = files_captured.get("photo")
    if isinstance(photo_val, (bytes, bytearray)):
        assert bytes(photo_val) == photo_bytes, (
            f"files['photo'] bytes must equal the sent PNG bytes, "
            f"got size {len(photo_val)}"
        )
    elif isinstance(photo_val, (list, tuple)):
        # e.g. ("image.png", b"...", "image/png")
        raw = photo_val[1] if len(photo_val) > 1 else photo_val[0]
        assert bytes(raw) == photo_bytes, (
            "files['photo'] tuple bytes must equal the sent PNG bytes"
        )
    else:
        pytest.fail(
            f"files['photo'] must be bytes or a (name, bytes, mime) tuple, "
            f"got {type(photo_val)}: {photo_val!r}"
        )


# ===========================================================================
# 7. Validation: missing chat_id → 422
# ===========================================================================


def test_m12b_telegram_photo_validation_missing_chat_id_422(gw_client: TestClient):
    """POST /publish/telegram-photo without chat_id form field → 422
    (FastAPI/Pydantic Form validation).
    """
    resp = gw_client.post(
        _PHOTO_URL,
        data={"caption": "عکس"},
        files={"photo": ("image.png", _SAMPLE_PNG, "image/png")},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 422, (
        f"missing chat_id must return 422, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 8. Validation: missing photo file → 422
# ===========================================================================


def test_m12b_telegram_photo_validation_missing_photo_422(gw_client: TestClient):
    """POST /publish/telegram-photo without the photo file field → 422
    (FastAPI/Pydantic UploadFile validation).
    """
    resp = gw_client.post(
        _PHOTO_URL,
        data={"chat_id": "55", "caption": ""},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 422, (
        f"missing photo file must return 422, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 9. Cross-leg idempotency (rule 8): same request_id never double-sends
# ===========================================================================


def test_m12b_telegram_photo_request_id_dedupes(gw_client: TestClient):
    """Two photo posts with the SAME request_id → second returns the cached
    response and _SENT gains exactly ONE entry (tunnel-drop retry safety)."""
    from rpim_model_gateway import telegram as _tg

    _tg._SENT.clear()
    request_id = f"job-{_secrets.token_hex(8)}"
    for _ in range(2):
        resp = gw_client.post(
            _PHOTO_URL,
            data={"chat_id": "77", "caption": "کپشن", "request_id": request_id},
            files={"photo": ("post.png", b"\x89PNG\r\n\x1a\nDEDUP", "image/png")},
            headers={"X-Internal-Token": _VALID_TOKEN},
        )
        assert resp.status_code == 200, f"photo send failed: {resp.text}"
        assert resp.json().get("ok") is True
    assert len(_tg._SENT) == 1, (
        f"same request_id must send exactly once (rule 8), got {len(_tg._SENT)}: {_tg._SENT}"
    )


def test_m12b_telegram_text_request_id_dedupes(gw_client: TestClient):
    """Same for the text endpoint: request_id dedupes the cross-leg retry."""
    from rpim_model_gateway import telegram as _tg

    _tg._SENT.clear()
    request_id = f"job-{_secrets.token_hex(8)}"
    for _ in range(2):
        resp = gw_client.post(
            "/publish/telegram",
            json={"chat_id": "78", "text": "سلام", "request_id": request_id},
            headers={"X-Internal-Token": _VALID_TOKEN},
        )
        assert resp.status_code == 200, f"text send failed: {resp.text}"
    assert len(_tg._SENT) == 1, (
        f"same request_id must send exactly once (rule 8), got {len(_tg._SENT)}: {_tg._SENT}"
    )
