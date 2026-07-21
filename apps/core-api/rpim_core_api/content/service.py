"""Draft generation service (M23, design §3.3).

The ONE path both the human route and the watchdog use: brain retrieval,
brand-profile system prompt, learnings injection (M22 slice C), T2
completion, unsourced-claim tripwire. HTTP concerns stay in the routers —
dependency outages surface as GenerationUnavailable with a stage tag so
each caller keeps its own contract (route → stage-specific 503, scan →
skip the tenant and keep the beat alive).
"""

import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.brain.service import BrandBrain
from rpim_core_api.content.complete_client import complete
from rpim_core_api.measurement import distiller
from rpim_core_api.models import BrandProfile, ContentDraft

_NUM_RE = re.compile(r"[0-9۰-۹]{2,}")


class GenerationUnavailable(Exception):
    """Embeddings or the model gateway are down (cold/slow after redeploy)."""

    def __init__(self, stage: str):
        self.stage = stage  # "embed" | "complete"
        super().__init__(stage)


def generate_draft(
    session: Session,
    tenant_id: str,
    brief: dict,
    origin: str = "human",
    commit: bool = True,
) -> ContentDraft:
    """Generate + persist one draft for this tenant (rule 6: caller-scoped).

    `origin` is the rule-1 transparency tag: "human" for the route,
    "agent" for the watchdog — the reviewer always sees who proposed.
    `commit=False` only flushes: the watchdog persists the draft and its
    audit row in ONE transaction, so a crash-replayed scan can never leave
    an orphan draft that dodges the dedupe (rule 8)."""
    profile = session.scalar(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)  # rule 6
    )

    query = " ".join(
        filter(None, [brief.get("goal"), brief.get("audience"), brief.get("hook") or ""])
    )
    brain = BrandBrain(session, tenant_id)
    try:
        chunks = brain.retrieve(query, k=5)
    except httpx.HTTPError as exc:
        # Same operational condition as brain ingest (cold/slow embeddings
        # after a redeploy) — this exact path killed the pilot's first draft.
        raise GenerationUnavailable("embed") from exc

    context_block = brain.compose_context(chunks)
    # Final-output-only contract (ADR 0031 + pilot A0 reject signals): the
    # model opened drafts with meta-preambles and option menus. The contract
    # lives in the system prompt AND as the prompt's last line.
    system = (
        "تو نویسنده محتوای برند هستی. لحن برند: "
        + ((profile.tone or "رسمی و روشن") if profile else "رسمی و روشن")
        + "\nفقط از «زمینه برند» استفاده کن؛ هیچ ادعا، قیمت یا مشخصه‌ای خارج از زمینه نیاور."
        + (
            "\nادعاهای ممنوع: " + "، ".join(profile.forbidden_claims)
            if profile and profile.forbidden_claims
            else ""
        )
        + "\nخروجی تو عیناً به‌عنوان متن پست استفاده می‌شود. فقط متن نهایی خود پست"
        " را بنویس: بدون مقدمه، بدون بازگویی بریف، بدون توضیح درباره‌ی متن،"
        " بدون ارائه‌ی چند گزینه و بدون عنوان یا برچسب متا. از اولین کلمه تا"
        " آخرین کلمه باید قابل انتشار باشد."
    )
    # M22 slice C (ADR 0043): the latest ACTIVE learned directives ride the
    # system prompt as a capped, template-only section — tenant strings can
    # never reach here (the distiller's injection boundary).
    learning = distiller.latest_active(session, tenant_id)
    if learning is not None:
        system += distiller.render_section(learning.directives)

    prompt = (
        f"زمینه برند:\n{context_block}\n\n"
        f"بریف: هدف={brief.get('goal')} | مخاطب={brief.get('audience')} | "
        f"کانال={brief.get('channel')} | قالب={brief.get('format')}"
        + (f" | قلاب={brief.get('hook')}" if brief.get("hook") else "")
        + (f" | فراخوان={brief.get('cta')}" if brief.get("cta") else "")
        + "\n\nحالا فقط متن نهایی پست را بنویس. با خود پست شروع کن، نه با توضیح یا مقدمه."
    )
    # Final content runs on T2 (ADR 0031 — the eval-gated tier).
    try:
        text = complete(prompt, system=system, tenant_id=tenant_id, task="t2")
    except httpx.HTTPError as exc:
        raise GenerationUnavailable("complete") from exc

    # Cheap unsourced-claim tripwire (full claim-check is M5 QA): any multi-
    # digit number in the draft that never appears in the context gets flagged.
    context_numbers = set(_NUM_RE.findall(context_block))
    flag_unsourced = any(n not in context_numbers for n in _NUM_RE.findall(text))

    draft = ContentDraft(
        tenant_id=tenant_id,
        brief=brief,
        context_refs=[c["source_title"] for c in chunks],
        text=text,
        flag_unsourced=flag_unsourced,
        status="draft",
        origin=origin,
    )
    session.add(draft)
    if commit:
        session.commit()
    else:
        session.flush()  # populate draft.id for same-transaction FK links
    return draft
