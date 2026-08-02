"""
M22 slice F acceptance tests — GA4 live transport (ADR 0049).

Contract:
  measurement/ga4_live.py — REST + service-account JWT, ZERO new deps
  (PyJWT/cryptography/httpx are already here):
    - fetch_day(credentials_path, property_id, day) POSTs the official
      Data API runReport for ONE day: dimension sessionCampaignName,
      metrics sessions + engagedSessions. Mapping (documented): clicks :=
      campaign-attributed sessions (the click-throughs that landed),
      sessions := engagedSessions (the quality signal).
    - "(not set)"/"(direct)" rows are dropped — direct traffic is not a
      campaign and must never poison campaign_channel_metrics.
    - The OAuth token is cached across calls (one exchange per ~55 min,
      not one per day of backfill).
  analytics_providers._ga4_fetch_day live branch calls the transport and
  wraps ANY failure as AnalyticsProviderError with the exception CLASS
  NAME only — no token, no property id, no values in errors (rule 4).
  Ops surface: UMAMI_* env NAMES land in .env.iran.example and the
  go-live runbook exists (docs/ops/go-live.md).

All tests named test_m22f_<criterion>.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from rpim_core_api.measurement import analytics_providers as providers
from rpim_core_api.measurement import ga4_live

_REPO_ROOT = Path(__file__).resolve().parents[3]

# A throwaway RSA key generated per test run — never a committed secret.
_TEST_KEY_PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
)


def _write_sa_file(tmp_path: Path) -> str:
    path = tmp_path / "sa.json"
    path.write_text(
        json.dumps(
            {
                "client_email": "svc@test-project.iam.gserviceaccount.com",
                "private_key": _TEST_KEY_PEM,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        encoding="utf-8",
    )
    return str(path)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, url: str = ""):
        self.status_code = status_code
        self._payload = payload
        self._url = url

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx  # noqa: PLC0415

            # Mirror PRODUCTION httpx: the error string carries the full
            # request URL — including the property id (the leak vector the
            # provider layer must contain).
            request = httpx.Request("POST", self._url or "https://x.test/")
            raise httpx.HTTPStatusError(
                f"Client error '{self.status_code}' for url '{self._url}'",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


def _wire(monkeypatch, tmp_path, report_payload, report_status=200) -> dict:
    """Point GA4 live at fakes; return a recorder of outbound requests."""
    calls: dict = {"token": 0, "report": [], "headers": []}

    def fake_post(url, **kwargs):
        if "oauth2" in url:
            calls["token"] += 1
            return _FakeResponse(200, {"access_token": "tok-test", "expires_in": 3600})
        calls["report"].append({"url": url, "json": kwargs.get("json")})
        calls["headers"].append(kwargs.get("headers", {}))
        return _FakeResponse(report_status, report_payload, url=url)

    monkeypatch.setattr(ga4_live.httpx, "post", fake_post)
    monkeypatch.setenv("GA4_MODE", "live")
    monkeypatch.setenv("GA4_CREDENTIALS_FILE", _write_sa_file(tmp_path))
    ga4_live._TOKEN_CACHE.clear()
    return calls


_REPORT = {
    "rows": [
        {
            "dimensionValues": [{"value": "spring-sale"}],
            "metricValues": [{"value": "12"}, {"value": "9"}],
        },
        {
            "dimensionValues": [{"value": "(not set)"}],
            "metricValues": [{"value": "80"}, {"value": "70"}],
        },
    ]
}


# ===========================================================================
# 1. The live transport
# ===========================================================================


def test_m22f_live_transport_fetches_and_maps_rows(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, tmp_path, _REPORT)
    rows = providers.ANALYTICS_PROVIDERS["ga4"]("123456", "2026-07-20")

    assert rows == [{"campaign": "spring-sale", "clicks": 12, "sessions": 9}], (
        "clicks := campaign sessions, sessions := engagedSessions; "
        "(not set) is direct traffic, never a campaign"
    )
    report = calls["report"][0]
    assert "properties/123456:runReport" in report["url"]
    assert report["json"]["dateRanges"] == [
        {"startDate": "2026-07-20", "endDate": "2026-07-20"}
    ]
    assert report["json"]["dimensions"] == [{"name": "sessionCampaignName"}]
    assert calls["headers"][0]["Authorization"] == "Bearer tok-test"


def test_m22f_token_is_cached_across_days(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, tmp_path, _REPORT)
    providers.ANALYTICS_PROVIDERS["ga4"]("123456", "2026-07-18")
    providers.ANALYTICS_PROVIDERS["ga4"]("123456", "2026-07-19")
    assert calls["token"] == 1, "a 7-day backfill must not do 7 token exchanges"
    assert len(calls["report"]) == 2


# ===========================================================================
# 2. Failure hygiene — provider error, class name only (rule 4)
# ===========================================================================


def test_m22f_transport_http_failure_is_a_provider_error(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, {"error": "forbidden"}, report_status=403)
    with pytest.raises(providers.AnalyticsProviderError) as excinfo:
        providers.ANALYTICS_PROVIDERS["ga4"]("123456", "2026-07-20")
    message = str(excinfo.value)
    assert "tok-test" not in message and "123456" not in message, (
        "no values in errors — class name only (rule 4)"
    )
    # The httpx error STRING carries the request URL (with the property
    # id) in production — the cause chain must be severed so Sentry /
    # logging.exception can never surface it (blueprint finding).
    assert excinfo.value.__cause__ is None and excinfo.value.__context__ is None, (
        "the original exception must not ride the chain out of the provider"
    )


def test_m22f_malformed_credentials_file_is_a_provider_error(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("GA4_MODE", "live")
    monkeypatch.setenv("GA4_CREDENTIALS_FILE", str(bad))
    ga4_live._TOKEN_CACHE.clear()
    with pytest.raises(providers.AnalyticsProviderError):
        providers.ANALYTICS_PROVIDERS["ga4"]("123456", "2026-07-20")


def test_m22f_malformed_report_payload_is_a_provider_error(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, {"rows": [{"broken": True}]})
    with pytest.raises(providers.AnalyticsProviderError):
        providers.ANALYTICS_PROVIDERS["ga4"]("123456", "2026-07-20")


# ===========================================================================
# 3. Ops surfaces — env names + go-live runbook
# ===========================================================================


def test_m22f_env_example_names_umami_vars():
    text = (_REPO_ROOT / ".env.iran.example").read_text("utf-8")
    for var in ("UMAMI_URL", "UMAMI_SITE_ID", "UMAMI_API_KEY"):
        assert re.search(rf"^{var}=", text, re.MULTILINE), (
            f".env.iran.example must name {var} (rule 4)"
        )


def test_m22f_go_live_runbook_exists():
    runbook = _REPO_ROOT / "docs" / "ops" / "go-live.md"
    assert runbook.exists(), "the operator go-live checklist ships in the repo"
    text = runbook.read_text("utf-8")
    for anchor in ("PUBLISH_MODE", "GA4_CREDENTIALS_FILE", "autonomy", "UMAMI_URL"):
        assert anchor in text, f"go-live runbook must cover {anchor}"
