"""
M7B acceptance tests — channel adapters in live mode.

Contract for rpim_core_api.publisher.channels when PUBLISH_MODE=live.

The module must expose a module-level HTTP seam:
    _post_json(url: str, payload: dict, headers: dict | None = None) -> None
that raises ChannelSendError on any transport/non-2xx failure. Live sends must
route through it. Tests monkeypatch channels._post_json to capture calls.

PUBLISH_MODE=live is set inside each test via monkeypatch.setenv so that
send() reads the env at call time (confirmed: channels.py reads
os.environ.get("PUBLISH_MODE", "fake") at call time, not at import time).

No literal secrets in repo (CLAUDE.md rule 4) — tokens generated per-test via
secrets.token_hex.

All tests named test_m7b_<criterion>.
"""

from __future__ import annotations

import secrets

import pytest

import rpim_core_api.publisher.channels as channels
from rpim_core_api.publisher.channels import ChannelSendError


def _clear_outbox() -> None:
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()


# ===========================================================================
# 1. Bale live adapter: _post_json called with correct URL and payload
# ===========================================================================


def test_m7b_bale_live_posts_to_correct_url(monkeypatch):
    """PUBLISH_MODE=live, BALE_BOT_TOKEN set → _post_json called once with the
    Bale API URL and {"chat_id", "text"} payload.

    Cross-leg rule: Bale sends directly from the iran leg (not via gateway).
    Expected URL: https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage
    """
    _clear_outbox()
    token = secrets.token_hex(16)
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("BALE_BOT_TOKEN", token)

    captured: dict = {}

    def fake_post_json(url: str, payload: dict, headers: dict | None = None) -> None:
        captured["url"] = url
        captured["payload"] = dict(payload)
        captured["headers"] = headers
        captured["calls"] = captured.get("calls", 0) + 1

    monkeypatch.setattr(channels, "_post_json", fake_post_json)

    channels.send("bale", "123", "متن", "job1")

    assert captured.get("calls") == 1, (
        f"_post_json must be called exactly once for bale send, "
        f"got: {captured.get('calls')}"
    )
    expected_url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    assert captured.get("url") == expected_url, (
        f"bale url must be {expected_url!r}, got {captured.get('url')!r}"
    )
    assert captured.get("payload") == {"chat_id": "123", "text": "متن"}, (
        f"bale payload must be {{chat_id, text}}, got {captured.get('payload')!r}"
    )


# ===========================================================================
# 2. Eitaa live adapter: _post_json called with correct URL and payload
# ===========================================================================


def test_m7b_eitaa_live_posts_to_correct_url(monkeypatch):
    """PUBLISH_MODE=live, EITAA_BOT_TOKEN set → _post_json called once with the
    Eitaayar API URL and {"chat_id", "text"} payload.

    Expected URL: https://eitaayar.ir/api/{EITAA_BOT_TOKEN}/sendMessage
    """
    _clear_outbox()
    token = secrets.token_hex(16)
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("EITAA_BOT_TOKEN", token)

    captured: dict = {}

    def fake_post_json(url: str, payload: dict, headers: dict | None = None) -> None:
        captured["url"] = url
        captured["payload"] = dict(payload)
        captured["calls"] = captured.get("calls", 0) + 1

    monkeypatch.setattr(channels, "_post_json", fake_post_json)

    channels.send("eitaa", "456", "پیام", "job2")

    assert captured.get("calls") == 1, (
        f"_post_json must be called exactly once for eitaa send, "
        f"got: {captured.get('calls')}"
    )
    expected_url = f"https://eitaayar.ir/api/{token}/sendMessage"
    assert captured.get("url") == expected_url, (
        f"eitaa url must be {expected_url!r}, got {captured.get('url')!r}"
    )
    assert captured.get("payload") == {"chat_id": "456", "text": "پیام"}, (
        f"eitaa payload must be {{chat_id, text}}, got {captured.get('payload')!r}"
    )


# ===========================================================================
# 3. Telegram live adapter: routes via US-leg gateway with X-Internal-Token
# ===========================================================================


def test_m7b_telegram_live_routes_via_gateway(monkeypatch):
    """PUBLISH_MODE=live, GATEWAY_URL and INTERNAL_TOKEN set → _post_json called
    once with the gateway's /publish/telegram URL and X-Internal-Token header.

    Telegram is cross-leg (CLAUDE.md rule 5): the iran leg MUST NOT call
    api.telegram.org directly. It forwards to the US-leg gateway, which makes
    the actual Telegram API call.

    Expected URL: {GATEWAY_URL}/publish/telegram
    Expected headers: {"X-Internal-Token": <INTERNAL_TOKEN>}
    """
    _clear_outbox()
    gateway_url = "http://gw.test:8080"
    internal_token = secrets.token_hex(16)
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("GATEWAY_URL", gateway_url)
    monkeypatch.setenv("INTERNAL_TOKEN", internal_token)

    captured: dict = {}

    def fake_post_json(url: str, payload: dict, headers: dict | None = None) -> None:
        captured["url"] = url
        captured["payload"] = dict(payload)
        captured["headers"] = dict(headers) if headers else {}
        captured["calls"] = captured.get("calls", 0) + 1

    monkeypatch.setattr(channels, "_post_json", fake_post_json)

    channels.send("telegram", "789", "سلام", "job3")

    assert captured.get("calls") == 1, (
        f"_post_json must be called exactly once for telegram send, "
        f"got: {captured.get('calls')}"
    )
    expected_url = f"{gateway_url}/publish/telegram"
    assert captured.get("url") == expected_url, (
        f"telegram must route to gateway url {expected_url!r}, "
        f"got {captured.get('url')!r}"
    )
    assert captured.get("payload") == {"chat_id": "789", "text": "سلام"}, (
        f"telegram payload must be {{chat_id, text}}, got {captured.get('payload')!r}"
    )
    assert captured.get("headers", {}).get("X-Internal-Token") == internal_token, (
        f"X-Internal-Token header must equal INTERNAL_TOKEN env value; "
        f"got headers: {captured.get('headers')!r}"
    )


# ===========================================================================
# 4. Missing token: ChannelSendError names the ENV VAR, not a secret value
# ===========================================================================


def test_m7b_bale_missing_token_raises_with_var_name(monkeypatch):
    """PUBLISH_MODE=live, BALE_BOT_TOKEN unset → ChannelSendError raised and
    str(exc) contains 'BALE_BOT_TOKEN' (var name only, never a token value).

    Constitution rule 4: credentials must never appear in log output or error
    messages; only the ENV VAR NAME is acceptable.
    """
    _clear_outbox()
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.delenv("BALE_BOT_TOKEN", raising=False)

    with pytest.raises(ChannelSendError) as exc_info:
        channels.send("bale", "123", "متن", "job4")

    err_str = str(exc_info.value)
    assert "BALE_BOT_TOKEN" in err_str, (
        f"ChannelSendError must mention env var name 'BALE_BOT_TOKEN', "
        f"got: {err_str!r}"
    )


# ===========================================================================
# 5. Transport failure: ChannelSendError propagates (job-not-lost semantics)
# ===========================================================================


def test_m7b_transport_failure_propagates_channel_send_error(monkeypatch):
    """_post_json raises ChannelSendError → send() must propagate it unchanged.

    Job-not-lost semantics: the caller (publish engine) must receive the error
    so it can mark the job as failed-and-retry rather than silently dropping it
    (CLAUDE.md rule 2: silence flag and publish engine both check the queue
    before sending; a lost error == a lost job == silent data loss).
    """
    _clear_outbox()
    token = secrets.token_hex(16)
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("BALE_BOT_TOKEN", token)

    def failing_post_json(url: str, payload: dict, headers: dict | None = None) -> None:
        raise ChannelSendError("simulated transport failure")

    monkeypatch.setattr(channels, "_post_json", failing_post_json)

    with pytest.raises(ChannelSendError):
        channels.send("bale", "123", "متن", "job5")


# ===========================================================================
# 6. Fake mode untouched: regression guard for the slice A seam
# ===========================================================================


def test_m7b_fake_mode_still_appends_to_outbox(monkeypatch):
    """PUBLISH_MODE=fake → send() appends to _OUTBOX as before.

    Regression guard: the live-mode wiring introduced in M7B must not alter
    the fake seam relied upon by all other test files (test_m7_publish.py,
    test_m5_qa.py, test_m6_queue.py).
    """
    _clear_outbox()
    monkeypatch.setenv("PUBLISH_MODE", "fake")

    channels.send("bale", "999", "رگرسیون", "job6")

    assert len(channels._OUTBOX) == 1, (
        f"_OUTBOX must have 1 entry after fake-mode send, got: {channels._OUTBOX}"
    )
    entry = channels._OUTBOX[0]
    assert entry.get("channel") == "bale", f"channel mismatch in _OUTBOX: {entry}"
    assert entry.get("chat_id") == "999", f"chat_id mismatch in _OUTBOX: {entry}"
    assert entry.get("text") == "رگرسیون", f"text mismatch in _OUTBOX: {entry}"
    assert entry.get("job_id") == "job6", f"job_id mismatch in _OUTBOX: {entry}"
