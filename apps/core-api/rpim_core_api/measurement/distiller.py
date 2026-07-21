"""Deterministic learning distiller (M22 slice C, ADR 0043) — pure rules, NO LLM.

The closed loop's write-side stays auditable and replayable: same evidence
in, same directives out, every version content-hashed (rule 8).

THE INJECTION BOUNDARY lives in this module: tenant-supplied strings
(campaign codes, reject notes) NEVER enter directive text or prompts —
`text_fa` comes ONLY from the fixed templates below. Raw codes stay in the
evidence JSON for audit, which is never prompt material.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.models import ApprenticeEvent, CampaignChannelMetric, TenantLearning
from rpim_shared.tz import app_timezone, now_app

WINDOW_DAYS = 28
# A campaign needs this many sent posts before its CTR means anything.
MIN_POSTS_SAMPLE = 3
TONE_REJECTS_MIN = 3
FACT_REJECTS_MIN = 2
# Hard cap on the injected prompt section — learnings season the prompt,
# they must never crowd out the brand context or the output contract.
SECTION_CAP = 600

# The ONLY strings allowed to reach a prompt from this pipeline.
TEMPLATES: dict[str, dict] = {
    "low_ctr": {
        "text_fa": (
            "برخی کمپین‌های اخیر نرخ کلیک پایین‌تری از میانه برند داشتند؛"
            " قلاب ابتدای متن را قوی‌تر و فراخوان پایانی را صریح‌تر بنویس."
        ),
        "weight": 3,
    },
    "fact_grounding": {
        "text_fa": (
            "چند پیش‌نویس اخیر به دلیل ادعای بدون منبع رد شده‌اند؛ فقط ادعاهایی"
            " را بنویس که عیناً در «زمینه برند» آمده‌اند."
        ),
        "weight": 2,
    },
    "tone_adjust": {
        "text_fa": (
            "چند پیش‌نویس اخیر به دلیل لحن رد شده‌اند؛ به لحن تعریف‌شده برند"
            " دقیق‌تر پایبند باش و از اصطلاحات خارج از آن پرهیز کن."
        ),
        "weight": 1,
    },
}


def load_evidence(session: Session, tenant_id: str) -> dict:
    """Trailing-window snapshot for ONE tenant (rule 6: single-tenant scope).

    JSON-serializable so it lands verbatim in `tenant_learnings.evidence`:
    campaign aggregates keyed by the RAW campaign code (audit only — never
    prompt material) plus the A0 rejection counters."""
    since = now_app() - timedelta(days=WINDOW_DAYS)
    since_day = since.strftime("%Y-%m-%d")

    campaigns: dict[str, dict[str, int]] = {}
    metric_rows = session.scalars(
        select(CampaignChannelMetric).where(
            CampaignChannelMetric.tenant_id == tenant_id,  # rule 6
            CampaignChannelMetric.day >= since_day,
        )
    ).all()
    for row in metric_rows:
        agg = campaigns.setdefault(row.campaign_code, {"clicks": 0, "posts_sent": 0})
        agg["clicks"] += int(row.clicks or 0)
        # posts_sent is a point-in-time denominator (count of sent jobs at
        # capture), not a per-day increment — max, never sum.
        agg["posts_sent"] = max(agg["posts_sent"], int(row.posts_sent or 0))

    rejects: dict[str, int] = {}
    events = session.scalars(
        select(ApprenticeEvent)
        .where(
            ApprenticeEvent.tenant_id == tenant_id,  # rule 6
            ApprenticeEvent.kind == "rejected",
        )
        .order_by(ApprenticeEvent.created_at.desc())
        .limit(500)
    ).all()
    for event in events:
        created = event.created_at
        if created.tzinfo is None:
            # sqlite naive round-trip — reattach the app zone (ADR 0032).
            created = created.replace(tzinfo=app_timezone())
        if created < since:
            continue
        reason = str((event.payload or {}).get("reason_code") or "unknown")
        rejects[reason] = rejects.get(reason, 0) + 1

    return {"window_days": WINDOW_DAYS, "campaigns": campaigns, "rejects": rejects}


def distill_directives(snapshot: dict) -> list[dict]:
    """Pure and deterministic: the whole rule table, no side effects.

    low_ctr fires when a minimum-sample campaign sits STRICTLY below the
    tenant's median CTR — a single campaign IS the median and can never
    fail itself. tone/fact fire on A0 reject counters over thresholds."""
    directives: list[dict] = []

    sampled = {
        code: agg
        for code, agg in snapshot.get("campaigns", {}).items()
        if int(agg.get("posts_sent", 0)) >= MIN_POSTS_SAMPLE
    }
    if len(sampled) >= 2:
        ctrs = sorted(agg["clicks"] / agg["posts_sent"] for agg in sampled.values())
        mid = len(ctrs) // 2
        median = ctrs[mid] if len(ctrs) % 2 else (ctrs[mid - 1] + ctrs[mid]) / 2
        if any(agg["clicks"] / agg["posts_sent"] < median for agg in sampled.values()):
            directives.append({"key": "low_ctr", **TEMPLATES["low_ctr"]})

    rejects = snapshot.get("rejects", {})
    if int(rejects.get("tone", 0)) >= TONE_REJECTS_MIN:
        directives.append({"key": "tone_adjust", **TEMPLATES["tone_adjust"]})
    if int(rejects.get("fact", 0)) >= FACT_REJECTS_MIN:
        directives.append({"key": "fact_grounding", **TEMPLATES["fact_grounding"]})

    # Deterministic order → stable content hashes and stable prompt sections.
    directives.sort(key=lambda d: (-int(d["weight"]), str(d["key"])))
    return directives


def content_hash(directives: list[dict], evidence: dict) -> str:
    """Canonical digest for rule-8 no-op replays: unchanged inputs distill
    to the same hash, so the daily beat appends nothing."""
    canonical = json.dumps(
        {"directives": directives, "evidence": evidence},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def latest_active(session: Session, tenant_id: str) -> TenantLearning | None:
    """The one version prompts may inject: newest ACTIVE for this tenant.
    Retired versions are invisible here forever — and because a same-hash
    re-distill is a no-op, the beat cannot resurrect one."""
    return session.scalar(
        select(TenantLearning)
        .where(
            TenantLearning.tenant_id == tenant_id,  # rule 6
            TenantLearning.status == "active",
        )
        .order_by(TenantLearning.version.desc())
        .limit(1)
    )


def render_section(directives: list[dict]) -> str:
    """The capped «آموخته‌های برند» block appended to the SYSTEM prompt.

    Whole directives drop lowest-weight-first to honor SECTION_CAP; the
    final hard slice only guards against pathological template edits."""
    kept = sorted(
        directives, key=lambda d: (-int(d.get("weight", 0)), str(d.get("key", "")))
    )
    if not kept:
        return ""

    def build(items: list[dict]) -> str:
        lines = "\n".join(f"- {d['text_fa']}" for d in items)
        return "\nآموخته‌های برند (از بازخورد قبلی مالک برند):\n" + lines

    section = build(kept)
    while len(section) > SECTION_CAP and len(kept) > 1:
        kept.pop()
        section = build(kept)
    return section[:SECTION_CAP]
