"""M16b — the gateway telegram sender honors a per-brand bot_token.

The iran leg forwards a connected brand's own token; absent → the us-leg
env token (the pre-hub global identity). rule 4: tokens only ever appear
in URLs at send time, never in errors.
"""

from __future__ import annotations

import pytest

from rpim_model_gateway import telegram


class _Resp:
    def raise_for_status(self):
        return None


@pytest.fixture()
def capture(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None, data=None, files=None):  # noqa: A002
        captured["url"] = url
        return _Resp()

    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setattr(httpx, "post", fake_post)
    return captured


def test_m16b_tenant_token_wins(capture, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-global")
    telegram.send_telegram("@x", "متن", bot_token="tenant-tok")
    assert "tenant-tok" in capture["url"] and "env-global" not in capture["url"], capture


def test_m16b_env_fallback_without_tenant_token(capture, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-global")
    telegram.send_telegram("@x", "متن")
    assert "env-global" in capture["url"], capture


def test_m16b_photo_honors_tenant_token(capture, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-global")
    telegram.send_telegram_photo("@x", "کپشن", b"png", bot_token="tenant-tok")
    assert "tenant-tok" in capture["url"], capture


def test_m16b_no_token_at_all_still_503_shaped(monkeypatch):
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(telegram.TelegramNotConfigured) as excinfo:
        telegram.send_telegram("@x", "متن")
    assert "TELEGRAM_BOT_TOKEN" in str(excinfo.value)
