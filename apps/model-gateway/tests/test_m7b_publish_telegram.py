"""
M7B acceptance tests — POST /publish/telegram on the model-gateway (US leg).

This endpoint is the cross-leg seam: the iran-leg channels adapter forwards
Telegram jobs here instead of calling api.telegram.org directly (CLAUDE.md
rule 5: official APIs from the US leg only; browser automation forbidden).

Auth contract: guarded by X-Internal-Token via the same _require_internal
helper used by /embed and /complete — inspected source returns 401 for
missing/wrong token (HTTPException status_code=401).

Module-level import of rpim_model_gateway.telegram is intentional:
  - it causes ModuleNotFoundError (collection error) until the telegram
    module is implemented — the expected failure mode during development.
  - once the module exists, _SENT and _post_json are directly accessible as
    module-level attributes for test-state control and seam monkeypatching.

PUBLISH_MODE is set to "fake" at module level before the app import so that
the /publish/telegram endpoint uses the in-process fake seam by default.
No literal secrets — INTERNAL_TOKEN and TELEGRAM_BOT_TOKEN generated via
secrets.token_hex per run (CLAUDE.md rule 4).

All tests named test_m7b_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

# Set env vars BEFORE any import of the gateway app (pattern from test_m2_embed.py,
# test_m3_complete.py). INTERNAL_TOKEN generated per run — no literal in repo.
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
# PUBLISH_MODE=fake → /publish/telegram uses in-process fake seam (no network).
os.environ.setdefault("PUBLISH_MODE", "fake")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# This import will raise ModuleNotFoundError until rpim_model_gateway.telegram
# is implemented — the expected collection error for M7B pre-implementation.
# ---------------------------------------------------------------------------
import rpim_model_gateway.telegram as _tg  # noqa: E402  # type: ignore[import]
from rpim_model_gateway.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_TOKEN: str = os.environ["INTERNAL_TOKEN"]
_TELEGRAM_URL = "/publish/telegram"
_VALID_BODY = {"chat_id": "55", "text": "سلام"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gw_client():
    """TestClient for the model-gateway app (same pattern as test_m3_complete.py)."""
    with TestClient(app) as c:
        yield c


# ===========================================================================
# 1. Auth guard: missing X-Internal-Token → 401
# ===========================================================================


def test_m7b_publish_telegram_missing_token_returns_401(gw_client: TestClient):
    """POST /publish/telegram without X-Internal-Token → 401.

    _require_internal raises HTTPException(status_code=401) for missing token
    (inspected from rpim_model_gateway.main._require_internal source).
    """
    resp = gw_client.post(_TELEGRAM_URL, json=_VALID_BODY)
    assert resp.status_code == 401, (
        f"expected 401 for missing X-Internal-Token, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 2. Auth guard: wrong X-Internal-Token → 401
# ===========================================================================


def test_m7b_publish_telegram_wrong_token_returns_401(gw_client: TestClient):
    """POST /publish/telegram with incorrect X-Internal-Token → 401."""
    resp = gw_client.post(
        _TELEGRAM_URL,
        json=_VALID_BODY,
        headers={"X-Internal-Token": "definitely-wrong-secret"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for wrong X-Internal-Token, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 3. Fake mode: valid request → 200 {"ok": true, ...}
# ===========================================================================


def test_m7b_publish_telegram_fake_mode_200_ok_true(
    gw_client: TestClient, monkeypatch
):
    """PUBLISH_MODE=fake, valid auth and body → 200 with {"ok": true}.

    Fake mode must not hit the Telegram network.
    """
    monkeypatch.setenv("PUBLISH_MODE", "fake")

    resp = gw_client.post(
        _TELEGRAM_URL,
        json=_VALID_BODY,
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 for fake-mode telegram send, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("ok") is True, (
        f"response must contain {{\"ok\": true}}, got: {body}"
    )


# ===========================================================================
# 4. Fake mode: entry recorded in _tg._SENT with chat_id and text
# ===========================================================================


def test_m7b_publish_telegram_fake_mode_records_in_sent_list(
    gw_client: TestClient, monkeypatch
):
    """PUBLISH_MODE=fake → entry appended to rpim_model_gateway.telegram._SENT
    containing the chat_id and text from the request body.
    """
    monkeypatch.setenv("PUBLISH_MODE", "fake")
    _tg._SENT.clear()

    chat_id = "55"
    text = "سلام"
    gw_client.post(
        _TELEGRAM_URL,
        json={"chat_id": chat_id, "text": text},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )

    assert len(_tg._SENT) == 1, (
        f"_SENT must have 1 entry after fake telegram send, got: {_tg._SENT}"
    )
    entry = _tg._SENT[0]
    assert entry.get("chat_id") == chat_id, (
        f"_SENT entry chat_id must be {chat_id!r}, got {entry.get('chat_id')!r}"
    )
    assert entry.get("text") == text, (
        f"_SENT entry text must be {text!r}, got {entry.get('text')!r}"
    )


# ===========================================================================
# 5. Live mode: TELEGRAM_BOT_TOKEN unset → 503 naming the env var
# ===========================================================================


def test_m7b_publish_telegram_live_token_unset_503_names_var(
    gw_client: TestClient, monkeypatch
):
    """PUBLISH_MODE=live, TELEGRAM_BOT_TOKEN unset → 503; detail must contain
    'TELEGRAM_BOT_TOKEN' (var name only, never a token value).

    Constitution rule 4: credentials must never appear in error output.
    """
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    resp = gw_client.post(
        _TELEGRAM_URL,
        json=_VALID_BODY,
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
# 6. Live seam: _post_json receives Telegram API URL with per-run token
# ===========================================================================


def test_m7b_publish_telegram_live_seam_url_and_payload(
    gw_client: TestClient, monkeypatch
):
    """PUBLISH_MODE=live, TELEGRAM_BOT_TOKEN set → rpim_model_gateway.telegram._post_json
    called with url == f"https://api.telegram.org/bot{token}/sendMessage" and
    payload containing chat_id and text.

    Per-run token from monkeypatch.setenv (CLAUDE.md rule 4: no literal secrets).
    """
    token = _secrets.token_hex(16)
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    captured: dict = {}

    def fake_post_json(url: str, payload: dict, headers: dict | None = None) -> None:
        captured["url"] = url
        captured["payload"] = dict(payload)

    monkeypatch.setattr(_tg, "_post_json", fake_post_json)

    resp = gw_client.post(
        _TELEGRAM_URL,
        json=_VALID_BODY,
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 for live seam test, got {resp.status_code}: {resp.text}"
    )
    expected_url = f"https://api.telegram.org/bot{token}/sendMessage"
    assert captured.get("url") == expected_url, (
        f"_post_json must be called with {expected_url!r}, "
        f"got {captured.get('url')!r}"
    )
    assert captured.get("payload", {}).get("chat_id") == _VALID_BODY["chat_id"], (
        f"_post_json payload must contain chat_id={_VALID_BODY['chat_id']!r}, "
        f"got payload: {captured.get('payload')!r}"
    )
    assert captured.get("payload", {}).get("text") == _VALID_BODY["text"], (
        f"_post_json payload must contain text={_VALID_BODY['text']!r}, "
        f"got payload: {captured.get('payload')!r}"
    )


# ===========================================================================
# 7. Validation: missing chat_id → 422
# ===========================================================================


def test_m7b_publish_telegram_validation_missing_chat_id_422(gw_client: TestClient):
    """POST /publish/telegram without chat_id → 422 (Pydantic validation)."""
    resp = gw_client.post(
        _TELEGRAM_URL,
        json={"text": "سلام"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 422, (
        f"missing chat_id must return 422, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 8. Validation: missing text → 422
# ===========================================================================


def test_m7b_publish_telegram_validation_missing_text_422(gw_client: TestClient):
    """POST /publish/telegram without text → 422 (Pydantic validation)."""
    resp = gw_client.post(
        _TELEGRAM_URL,
        json={"chat_id": "55"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 422, (
        f"missing text must return 422, got {resp.status_code}: {resp.text}"
    )
