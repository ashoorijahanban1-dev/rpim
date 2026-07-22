"""
M23b acceptance tests — autonomy dial + agent audit surfaces (ADR 0047).

Contract:
  Backend:
    - GET /agent/autonomy → {autonomy_level} (any authenticated role reads;
      raising stays owner-only via the existing PUT).
    - GET /agent/actions → tenant-scoped audit list, newest first:
      {kind, status, score, relevance, rationale, draft_id, created_at}.
    - THE LOOP CLOSES ON HUMAN VERDICTS: approving or editing an
      origin="agent" draft flips its agent_action to "accepted"; rejecting
      flips it to "dismissed" — in the SAME commit as the draft verdict.
      Human drafts (no action row) stay untouched, never crash.
  Dashboard (/insights hosts the governance surfaces):
    - Owner autonomy dial wired to PUT /agent/autonomy (levels 0..3 from
      fa.insights.level_* labels), API 403 surfaced via the error path.
    - Agent proposals list from GET /agent/actions with status chips.
    - Persian ONLY from fa.json; aria attributes present.

All tests named test_m23b_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "insights" / "page.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_PERSIAN_RE = re.compile(r"[؀-ۿ]")


def _session():
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415

    return Session(db_module.engine)


def _register(client: TestClient, email: str, name: str) -> tuple[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"], resp.json()["tenant_id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _propose_for(client: TestClient, token: str, tenant_id: str, keyword: str) -> str:
    """Drive one real watchdog proposal; return the agent draft id."""
    from rpim_core_api.models import TrendItem  # noqa: PLC0415

    with _session() as session:
        session.add(
            TrendItem(tenant_id=tenant_id, keyword=keyword, source="simulated", score=80)
        )
        session.commit()
    resp = client.post("/agent/scan", headers={"X-Internal-Token": _INTERNAL_TOKEN})
    assert resp.status_code == 200 and resp.json()["proposed"] == 1, resp.text
    drafts = client.get("/content/drafts", headers=_auth(token)).json()["drafts"]
    agent_drafts = [d for d in drafts if d["origin"] == "agent"]
    assert agent_drafts, "scan must have produced an agent draft"
    return agent_drafts[0]["draft_id"]


# ===========================================================================
# 1. Backend surfaces
# ===========================================================================


def test_m23b_autonomy_is_readable(client: TestClient):
    token, _tenant = _register(client, "m23b-read@example.com", "M23bRead")
    resp = client.get("/agent/autonomy", headers=_auth(token))
    assert resp.status_code == 200 and resp.json()["autonomy_level"] == 0, (
        "L0 default must be visible before any change"
    )
    client.put("/agent/autonomy", json={"level": 2}, headers=_auth(token))
    assert (
        client.get("/agent/autonomy", headers=_auth(token)).json()["autonomy_level"] == 2
    )


def test_m23b_actions_list_is_tenant_scoped(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token_a, tenant_a = _register(client, "m23b-list-a@example.com", "M23bListA")
    token_b, _tenant_b = _register(client, "m23b-list-b@example.com", "M23bListB")
    client.put("/agent/autonomy", json={"level": 1}, headers=_auth(token_a))
    _propose_for(client, token_a, tenant_a, "فهرست")

    items = client.get("/agent/actions", headers=_auth(token_a)).json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["kind"] == "brief_proposal" and entry["status"] == "proposed"
    assert entry["score"] == 80 and 0 <= entry["relevance"] <= 100
    assert _PERSIAN_RE.search(entry["rationale"]) and entry["draft_id"]
    assert entry["created_at"]

    assert client.get("/agent/actions", headers=_auth(token_b)).json()["items"] == [], (
        "rule 6: tenant B never sees A's audit trail"
    )


def test_m23b_approving_agent_draft_marks_accepted(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token, tenant_id = _register(client, "m23b-acc@example.com", "M23bAcc")
    client.put("/agent/autonomy", json={"level": 1}, headers=_auth(token))
    draft_id = _propose_for(client, token, tenant_id, "پذیرش")

    resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    items = client.get("/agent/actions", headers=_auth(token)).json()["items"]
    assert items[0]["status"] == "accepted", (
        "the human verdict closes the loop on the audit row"
    )


def test_m23b_rejecting_agent_draft_marks_dismissed(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token, tenant_id = _register(client, "m23b-dis@example.com", "M23bDis")
    client.put("/agent/autonomy", json={"level": 1}, headers=_auth(token))
    draft_id = _propose_for(client, token, tenant_id, "رد")

    resp = client.post(
        f"/content/drafts/{draft_id}/reject",
        json={"reason_code": "taste", "note": "آزمون"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    items = client.get("/agent/actions", headers=_auth(token)).json()["items"]
    assert items[0]["status"] == "dismissed"


def test_m23b_editing_agent_draft_marks_accepted(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token, tenant_id = _register(client, "m23b-edit@example.com", "M23bEdit")
    client.put("/agent/autonomy", json={"level": 1}, headers=_auth(token))
    draft_id = _propose_for(client, token, tenant_id, "ویرایش")

    resp = client.put(
        f"/content/drafts/{draft_id}",
        json={"edited_text": "متن ویرایش‌شده"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    items = client.get("/agent/actions", headers=_auth(token)).json()["items"]
    assert items[0]["status"] == "accepted", "an edit is acceptance with changes"


def test_m23b_human_draft_verdicts_never_touch_actions(client: TestClient):
    token, _tenant = _register(client, "m23b-hum@example.com", "M23bHum")
    brief = {
        "goal": "معرفی",
        "audience": "خانواده‌ها",
        "channel": "تلگرام",
        "format": "پست متنی",
        "hook": None,
        "cta": None,
    }
    draft_id = client.post(
        "/content/drafts", json={"brief": brief}, headers=_auth(token)
    ).json()["draft_id"]
    resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert resp.status_code == 200, "no action row exists — must not crash"
    assert client.get("/agent/actions", headers=_auth(token)).json()["items"] == []


# ===========================================================================
# 2. Dashboard surfaces (static)
# ===========================================================================


def test_m23b_insights_page_hosts_the_autonomy_dial():
    src = _PAGE_TSX.read_text("utf-8")
    assert "/agent/autonomy" in src, "the dial reads and writes /agent/autonomy"
    assert "autonomy" in src and "fa.insights." in src
    assert not _PERSIAN_RE.search(src), "locale-only rule"


def test_m23b_insights_page_lists_agent_actions():
    src = _PAGE_TSX.read_text("utf-8")
    assert "/agent/actions" in src, "the audit list rides GET /agent/actions"
    assert "rationale" in src, "the human sees WHY each proposal exists"


def test_m23b_fa_locale_carries_the_agent_sections():
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    section = fa.get("insights", {})
    for key in (
        "autonomy_title",
        "autonomy_hint",
        "autonomy_saved",
        "level_0",
        "level_1",
        "level_2",
        "level_3",
        "agent_title",
        "agent_hint",
        "agent_empty",
        "score_label",
        "relevance_label",
        "status_proposed",
        "status_accepted",
        "status_dismissed",
    ):
        assert section.get(key), f"fa.insights.{key} missing/empty"
        assert _PERSIAN_RE.search(section[key]), f"fa.insights.{key} must be Persian"
