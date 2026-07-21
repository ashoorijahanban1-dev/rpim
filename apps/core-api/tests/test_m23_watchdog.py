"""
M23a acceptance tests — the autonomous watchdog core (last pentarchy pillar).

Contract (design §0018/§2/§3.6, ADR 0046):
  Schema (migration 0018, chain after 0020): tenants.autonomy_level
  (default 0 = L0), content_drafts.origin (human | agent), agent_actions
  with UNIQUE(tenant_id, trend_item_id, kind) — a trend is proposed at
  most once (rule 8).

  POST /agent/scan (X-Internal-Token, 30-min beat) per tenant:
    - autonomy_level >= 1 required — L0 (the default) NEVER proposes:
      existing tenants opt IN, the watchdog ships inert.
    - silence/kill halt (rule 2 spirit): a halted tenant spends nothing.
    - AGENT_DAILY_DRAFTS cap per app-clock day (ADR 0032).
    - brand-relevance gate: relevance = 100 * best cosine hit on
      product/claim chunks; below AGENT_MIN_RELEVANCE → skip entirely
      (no draft, no T2 spend, no action row).
    - proposal = agent_actions row (heat score, relevance, fa rationale)
      + a content_drafts row with origin="agent" through the SAME
      generate_draft path humans use (learnings injection included).
    - counts-only response; replays dedupe (rule 8).

  PUT /agent/autonomy — OWNER-only (M24 RBAC), level 0..3.
  Surfaces: drafts payloads carry origin; the queue page shows an agent
  badge from fa.queue.agent_badge; /export bumps to v5 with origin +
  agent_actions; env NAMES documented (rule 4).

All tests named test_m23_<criterion>.
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
_QUEUE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "queue" / "page.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"
_ENV_IRAN = _REPO_ROOT / ".env.iran.example"

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


def _internal() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _seed_trend(tenant_id: str, keyword: str, score: int) -> None:
    from rpim_core_api.models import TrendItem  # noqa: PLC0415

    with _session() as session:
        session.add(
            TrendItem(tenant_id=tenant_id, keyword=keyword, source="simulated", score=score)
        )
        session.commit()


def _set_autonomy(client: TestClient, token: str, level: int) -> None:
    resp = client.put("/agent/autonomy", json={"level": level}, headers=_auth(token))
    assert resp.status_code == 200, resp.text


def _scan(client: TestClient) -> dict:
    resp = client.post("/agent/scan", headers=_internal())
    assert resp.status_code == 200, resp.text
    return resp.json()


def _actions_for(tenant_id: str) -> list:
    from sqlalchemy import select  # noqa: PLC0415

    from rpim_core_api.models import AgentAction  # noqa: PLC0415

    with _session() as session:
        return list(
            session.scalars(select(AgentAction).where(AgentAction.tenant_id == tenant_id))
        )


# ===========================================================================
# 1. Gates: token, autonomy opt-in, RBAC on the autonomy dial
# ===========================================================================


def test_m23_scan_requires_internal_token(client: TestClient):
    assert client.post("/agent/scan").status_code == 403


def test_m23_autonomy_is_owner_only_and_validated(client: TestClient):
    owner, _tenant = _register(client, "m23-aut@example.com", "M23Aut")
    invite = client.post(
        "/auth/invites",
        json={"email": "m23-aut-ed@example.com", "role": "editor"},
        headers=_auth(owner),
    ).json()["token"]
    editor = client.post(
        "/auth/invites/accept", json={"token": invite, "password": "Password123!"}
    ).json()["access_token"]

    assert (
        client.put("/agent/autonomy", json={"level": 1}, headers=_auth(editor)).status_code
        == 403
    ), "raising autonomy is a governance act — owner-only (M24 RBAC)"
    assert (
        client.put("/agent/autonomy", json={"level": 4}, headers=_auth(owner)).status_code
        == 422
    ), "levels are L0..L3"
    _set_autonomy(client, owner, 1)


def test_m23_l0_default_never_proposes(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    _token, tenant_id = _register(client, "m23-l0@example.com", "M23L0")
    _seed_trend(tenant_id, "ترند-داغ", score=90)

    result = _scan(client)
    assert result["proposed"] == 0, "L0 is the shipped default: watchdog stays inert"
    assert _actions_for(tenant_id) == []


# ===========================================================================
# 2. The proposal loop: propose, dedupe, gate, halt, cap, isolate
# ===========================================================================


def test_m23_scan_proposes_agent_draft_with_rationale(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token, tenant_id = _register(client, "m23-go@example.com", "M23Go")
    _set_autonomy(client, token, 1)
    _seed_trend(tenant_id, "هوش-مصنوعی", score=82)

    result = _scan(client)
    assert result["proposed"] == 1, result

    actions = _actions_for(tenant_id)
    assert len(actions) == 1
    action = actions[0]
    assert action.kind == "brief_proposal" and action.status == "proposed"
    assert action.score == 82 and 0 <= action.relevance <= 100
    assert action.draft_id, "the proposing action links its draft"
    assert _PERSIAN_RE.search(action.rationale), "the audit rationale is Persian"

    drafts = client.get("/content/drafts", headers=_auth(token)).json()["drafts"]
    assert len(drafts) == 1 and drafts[0]["origin"] == "agent", (
        "agent drafts surface their origin to the human (rule 1 transparency)"
    )
    assert drafts[0]["status"] == "draft", "proposals land in the NORMAL approval queue"


def test_m23_scan_replay_is_deduped(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token, tenant_id = _register(client, "m23-dedup@example.com", "M23Dedup")
    _set_autonomy(client, token, 1)
    _seed_trend(tenant_id, "تکرار", score=70)

    assert _scan(client)["proposed"] == 1
    assert _scan(client)["proposed"] == 0, "a trend is proposed at most once (rule 8)"
    assert len(_actions_for(tenant_id)) == 1
    drafts = client.get("/content/drafts", headers=_auth(token)).json()["drafts"]
    assert len(drafts) == 1


def test_m23_relevance_gate_skips_without_spend(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "35")
    token, tenant_id = _register(client, "m23-gate@example.com", "M23Gate")
    _set_autonomy(client, token, 1)
    _seed_trend(tenant_id, "بی‌ربط", score=95)  # hot but nothing in the brain

    result = _scan(client)
    assert result["proposed"] == 0
    assert _actions_for(tenant_id) == [], (
        "below the gate: no draft, no T2 spend, no action row — heat alone never spends"
    )
    drafts = client.get("/content/drafts", headers=_auth(token)).json()["drafts"]
    assert drafts == []


def test_m23_halted_tenant_is_skipped(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token, tenant_id = _register(client, "m23-halt@example.com", "M23Halt")
    _set_autonomy(client, token, 1)
    _seed_trend(tenant_id, "سکوت", score=88)
    resp = client.post(
        "/governance/silence", json={"active": True, "reason": "آزمون"}, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text

    result = _scan(client)
    assert result["proposed"] == 0, "silence halts the watchdog too (rule 2 spirit)"
    assert _actions_for(tenant_id) == []


def test_m23_daily_cap_bounds_proposals(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    monkeypatch.setenv("AGENT_DAILY_DRAFTS", "1")
    token, tenant_id = _register(client, "m23-cap@example.com", "M23Cap")
    _set_autonomy(client, token, 1)
    _seed_trend(tenant_id, "اول", score=90)
    _seed_trend(tenant_id, "دوم", score=80)

    result = _scan(client)
    assert result["proposed"] == 1, "the app-clock daily cap bounds reviewer load + spend"
    assert len(_actions_for(tenant_id)) == 1


def test_m23_scan_is_tenant_isolated(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token_a, tenant_a = _register(client, "m23-iso-a@example.com", "M23IsoA")
    token_b, tenant_b = _register(client, "m23-iso-b@example.com", "M23IsoB")
    _set_autonomy(client, token_a, 1)
    _seed_trend(tenant_a, "الف", score=75)

    _scan(client)
    assert len(_actions_for(tenant_a)) == 1
    assert _actions_for(tenant_b) == [], "rule 6: nothing bleeds across tenants"
    drafts_b = client.get("/content/drafts", headers=_auth(token_b)).json()["drafts"]
    assert drafts_b == []


# ===========================================================================
# 3. Surfaces: export v5, queue badge, env names
# ===========================================================================


def test_m23_export_v5_carries_origin_and_actions(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_MIN_RELEVANCE", "0")
    token, tenant_id = _register(client, "m23-exp@example.com", "M23Exp")
    _set_autonomy(client, token, 1)
    _seed_trend(tenant_id, "صادرات", score=66)
    _scan(client)

    body = client.get("/export", headers=_auth(token)).json()
    assert body["export_version"] == 5, "M23a bumps the export contract"
    assert body["drafts"][0]["origin"] == "agent"
    actions = body["agent_actions"]
    assert len(actions) == 1
    entry = actions[0]
    assert entry["kind"] == "brief_proposal" and entry["status"] == "proposed"
    assert entry["score"] == 66 and "rationale" in entry and entry["draft_id"]


def test_m23_queue_badge_rides_the_locale(client: TestClient):
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    badge = fa.get("queue", {}).get("agent_badge")
    assert badge and _PERSIAN_RE.search(badge), "fa.queue.agent_badge missing/empty"
    src = _QUEUE_TSX.read_text("utf-8")
    assert "agent_badge" in src and "origin" in src, (
        "the queue page badges agent drafts (rule 1 transparency)"
    )
    assert not _PERSIAN_RE.search(src), "locale-only rule"


def test_m23_env_names_are_documented(client: TestClient):
    env = _ENV_IRAN.read_text("utf-8")
    assert "AGENT_DAILY_DRAFTS" in env and "AGENT_MIN_RELEVANCE" in env, (
        "env NAMES ship in the example files (rule 4)"
    )
