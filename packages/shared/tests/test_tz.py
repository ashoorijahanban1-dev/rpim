"""App-timezone helper (ADR 0032) — PT default, env-reversible."""

from datetime import UTC, datetime

from rpim_shared.tz import app_timezone, month_key, now_app


def test_default_timezone_is_pacific(monkeypatch):
    monkeypatch.delenv("RPIM_TIMEZONE", raising=False)
    assert str(app_timezone()) == "America/Los_Angeles"


def test_env_override_is_the_revert_path(monkeypatch):
    monkeypatch.setenv("RPIM_TIMEZONE", "UTC")
    assert str(app_timezone()) == "UTC"


def test_now_app_is_aware(monkeypatch):
    monkeypatch.delenv("RPIM_TIMEZONE", raising=False)
    assert now_app().tzinfo is not None


def test_month_key_buckets_aware_stamps_in_app_tz(monkeypatch):
    monkeypatch.delenv("RPIM_TIMEZONE", raising=False)
    # 2026-07-01 02:00 UTC is still 2026-06-30 19:00 in Pacific.
    stamp = datetime(2026, 7, 1, 2, 0, tzinfo=UTC)
    assert month_key(stamp) == "2026-06"


def test_month_key_naive_stamps_taken_at_face_value(monkeypatch):
    monkeypatch.delenv("RPIM_TIMEZONE", raising=False)
    assert month_key(datetime(2026, 7, 1, 2, 0)) == "2026-07"
    assert month_key(None) is None
