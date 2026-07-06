"""
M5 acceptance tests — QA & Governance + Silence Mode.

Pure check functions under test (imported directly — no HTTP):
  rpim_core_api.qa.checks.check_claims
  rpim_core_api.qa.checks.check_sensitivity
  rpim_core_api.qa.checks.check_channel

HTTP routes under test:
  POST /qa/check/{draft_id}
  GET  /governance/status
  POST /governance/silence
  POST /governance/kill

All tests named test_m5_<criterion> and FAIL until the implementation
provides rpim_core_api.qa (ModuleNotFoundError) and the routes (404s).

env INTERNAL_TOKEN is generated here and set BEFORE any app import so the
governance implementation can read it from the environment (even at import
time). EMBED_MODE=fake and COMPLETE_MODE=fake keep tests offline.
"""

from __future__ import annotations

import os
import secrets

# INTERNAL_TOKEN must be set BEFORE any import of rpim_core_api.* (including
# the lazy import inside the `client` fixture). Module-level code in test
# files runs during pytest collection, which precedes fixture execution.
_INTERNAL_TOKEN: str = secrets.token_hex(32)
os.environ["INTERNAL_TOKEN"] = _INTERNAL_TOKEN

# Fake modes: no network calls, no model-gateway required in CI.
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers (mirror the pattern in test_m4_content.py)
# ---------------------------------------------------------------------------

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_draft(client: TestClient, token: str) -> str:
    """Create a content draft and return its draft_id."""
    resp = client.post(
        "/content/drafts",
        json={"brief": _BRIEF},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"draft creation failed: {resp.text}"
    return resp.json()["draft_id"]


# ===========================================================================
# 1. Pure function tests — check_claims
# ===========================================================================


def test_m5_check_claims_flags_western_digit_absent_from_context():
    """check_claims flags a multi-digit western-digit number present in text but
    absent from context; returns list with check=='claims', level=='review',
    and reason containing the offending number."""
    from rpim_core_api.qa.checks import check_claims  # type: ignore[import]

    flags = check_claims("قیمت محصول ما 5000 تومان است", "هیچ عددی وجود ندارد")
    assert len(flags) >= 1, f"Expected >= 1 flag for absent western number, got: {flags}"
    assert all(f["check"] == "claims" for f in flags), (
        f"All flags must have check=='claims': {flags}"
    )
    assert all(f["level"] == "review" for f in flags), (
        f"All claims flags must have level=='review': {flags}"
    )
    reasons = " ".join(f.get("reason", "") for f in flags)
    assert "5000" in reasons, (
        f"Offending number '5000' must appear in at least one reason, got: {flags}"
    )


def test_m5_check_claims_flags_persian_digit_absent_from_context():
    """check_claims flags a multi-digit Persian-digit number present in text but
    absent from context; reason must contain the offending number."""
    from rpim_core_api.qa.checks import check_claims  # type: ignore[import]

    flags = check_claims("تخفیف ۳۰ درصدی برای شما", "محصولات با کیفیت")
    assert len(flags) >= 1, (
        f"Expected >= 1 flag for absent Persian-digit number, got: {flags}"
    )
    assert flags[0]["check"] == "claims"
    assert flags[0]["level"] == "review"
    reasons = " ".join(f.get("reason", "") for f in flags)
    assert "۳۰" in reasons, (
        f"Offending number '۳۰' must appear in reason, got: {flags}"
    )


def test_m5_check_claims_no_flag_when_numbers_in_context():
    """check_claims returns [] when ALL numbers in text also appear in context."""
    from rpim_core_api.qa.checks import check_claims  # type: ignore[import]

    context = "قیمت محصول ۵۰۰۰ تومان و تخفیف ۳۰ درصد است"
    text = "ما محصول را به قیمت ۵۰۰۰ تومان با تخفیف ۳۰ درصد ارائه می‌دهیم"
    flags = check_claims(text, context)
    assert flags == [], (
        f"Expected no flags when all numbers are in context, got: {flags}"
    )


def test_m5_check_claims_no_flag_when_text_has_no_numbers():
    """check_claims returns [] when text contains no multi-digit numbers."""
    from rpim_core_api.qa.checks import check_claims  # type: ignore[import]

    flags = check_claims("برند ما بهترین خدمات را ارائه می‌دهد", "هیچ عددی نیست")
    assert flags == [], (
        f"Expected no flags for number-free text, got: {flags}"
    )


# ===========================================================================
# 2. Pure function tests — check_sensitivity
# ===========================================================================


def test_m5_check_sensitivity_political():
    """check_sensitivity flags 'انتخابات' as category=='political', level=='block'."""
    from rpim_core_api.qa.checks import check_sensitivity  # type: ignore[import]

    flags = check_sensitivity("در این انتخابات شرکت کنید")
    assert len(flags) >= 1, f"Expected flag for political keyword, got: {flags}"
    cats = [f["category"] for f in flags]
    assert "political" in cats, (
        f"Expected category 'political' in flags, got categories: {cats}"
    )
    political_flags = [f for f in flags if f["category"] == "political"]
    assert political_flags[0]["level"] == "block", (
        f"political flag must have level=='block': {political_flags[0]}"
    )
    assert political_flags[0]["check"] == "sensitivity", (
        f"flag must have check=='sensitivity': {political_flags[0]}"
    )


def test_m5_check_sensitivity_religious():
    """check_sensitivity flags 'تحریم مذهبی' style content as category=='religious',
    level=='block'."""
    from rpim_core_api.qa.checks import check_sensitivity  # type: ignore[import]

    flags = check_sensitivity("این برنامه با تحریم مذهبی روبرو شد")
    assert len(flags) >= 1, f"Expected flag for religious keyword, got: {flags}"
    cats = [f["category"] for f in flags]
    assert "religious" in cats, (
        f"Expected category 'religious' in flags, got categories: {cats}"
    )
    rel_flags = [f for f in flags if f["category"] == "religious"]
    assert rel_flags[0]["level"] == "block", (
        f"religious flag must have level=='block': {rel_flags[0]}"
    )


def test_m5_check_sensitivity_ethnic():
    """check_sensitivity flags 'قومیت' as category=='ethnic', level=='block'."""
    from rpim_core_api.qa.checks import check_sensitivity  # type: ignore[import]

    flags = check_sensitivity("تبعیض بر اساس قومیت پذیرفته نیست")
    assert len(flags) >= 1, f"Expected flag for ethnic keyword, got: {flags}"
    cats = [f["category"] for f in flags]
    assert "ethnic" in cats, (
        f"Expected category 'ethnic' in flags, got categories: {cats}"
    )
    eth_flags = [f for f in flags if f["category"] == "ethnic"]
    assert eth_flags[0]["level"] == "block", (
        f"ethnic flag must have level=='block': {eth_flags[0]}"
    )


def test_m5_check_sensitivity_gender():
    """check_sensitivity flags 'جنسیتی' as category=='gender', level=='block'."""
    from rpim_core_api.qa.checks import check_sensitivity  # type: ignore[import]

    flags = check_sensitivity("تبعیض جنسیتی در استخدام وجود دارد")
    assert len(flags) >= 1, f"Expected flag for gender keyword, got: {flags}"
    cats = [f["category"] for f in flags]
    assert "gender" in cats, (
        f"Expected category 'gender' in flags, got categories: {cats}"
    )
    gen_flags = [f for f in flags if f["category"] == "gender"]
    assert gen_flags[0]["level"] == "block", (
        f"gender flag must have level=='block': {gen_flags[0]}"
    )


def test_m5_check_sensitivity_health():
    """check_sensitivity flags 'درمان قطعی' as category=='health', level=='block'."""
    from rpim_core_api.qa.checks import check_sensitivity  # type: ignore[import]

    flags = check_sensitivity("این محصول درمان قطعی دیابت است")
    assert len(flags) >= 1, f"Expected flag for health keyword, got: {flags}"
    cats = [f["category"] for f in flags]
    assert "health" in cats, (
        f"Expected category 'health' in flags, got categories: {cats}"
    )
    hlth_flags = [f for f in flags if f["category"] == "health"]
    assert hlth_flags[0]["level"] == "block", (
        f"health flag must have level=='block': {hlth_flags[0]}"
    )


def test_m5_check_sensitivity_neutral_returns_empty():
    """check_sensitivity returns [] for a neutral marketing sentence."""
    from rpim_core_api.qa.checks import check_sensitivity  # type: ignore[import]

    flags = check_sensitivity(
        "محصول جدید ما با کیفیت بالا برای تمام مشتریان موجود است"
    )
    assert flags == [], (
        f"Neutral marketing text must return no sensitivity flags, got: {flags}"
    )


# ===========================================================================
# 3. Pure function tests — check_channel
# ===========================================================================


def test_m5_check_channel_within_cap_returns_empty():
    """check_channel returns [] when text length is within the channel cap."""
    from rpim_core_api.qa.checks import check_channel  # type: ignore[import]

    flags = check_channel("متن کوتاه تبلیغاتی", "telegram")
    assert flags == [], (
        f"Short text within channel cap must return [], got: {flags}"
    )


def test_m5_check_channel_over_cap_telegram():
    """check_channel returns a review-level flag when text exceeds Telegram 4096-char cap."""
    from rpim_core_api.qa.checks import check_channel  # type: ignore[import]

    long_text = "a" * 4097  # one character over the 4096 Telegram cap
    flags = check_channel(long_text, "telegram")
    assert len(flags) >= 1, (
        f"Text exceeding Telegram cap must get a flag, got: {flags}"
    )
    assert flags[0]["check"] == "channel", (
        f"flag must have check=='channel': {flags[0]}"
    )
    assert flags[0]["level"] == "review", (
        f"channel over-cap flag must have level=='review': {flags[0]}"
    )


def test_m5_check_channel_over_cap_instagram():
    """check_channel returns a review-level flag when text exceeds Instagram 2200-char cap."""
    from rpim_core_api.qa.checks import check_channel  # type: ignore[import]

    long_text = "a" * 2201  # one character over the 2200 Instagram cap
    flags = check_channel(long_text, "instagram")
    assert len(flags) >= 1, (
        f"Text exceeding Instagram cap must get a flag, got: {flags}"
    )
    assert flags[0]["check"] == "channel"
    assert flags[0]["level"] == "review"


def test_m5_check_channel_unknown_channel():
    """check_channel returns a review-level flag mentioning 'unknown' for an
    unrecognised channel name."""
    from rpim_core_api.qa.checks import check_channel  # type: ignore[import]

    flags = check_channel("هر متنی", "whatsapp")
    assert len(flags) >= 1, (
        f"Unknown channel must return a flag, got: {flags}"
    )
    assert flags[0]["check"] == "channel", (
        f"flag must have check=='channel': {flags[0]}"
    )
    assert flags[0]["level"] == "review", (
        f"unknown-channel flag must have level=='review': {flags[0]}"
    )
    # Rule 6: reasons are Persian for the dashboard; the machine marker
    # lives in the structured `code` field instead of English reason text.
    assert flags[0].get("code") == "unknown_channel", (
        f"flag must carry code=='unknown_channel' for unrecognised channel, got: {flags[0]}"
    )


# ===========================================================================
# 4. THE acceptance test: 20-sample trap set (§6.4 acceptance criterion)
# ===========================================================================


def test_m5_trap_set_all_flagged():
    """20-sample trap set: ALL samples must yield >= 1 flag.

    Blueprint §6.4: a 20-sample trap set (wrong prices, sensitive topics)
    must ALL get flagged.

    10 texts with wrong prices/numbers absent from context (mix Persian/western
    digits) + 10 sensitive texts (2 per category across the 5 categories).
    Sensitive samples must also have level=='block' on every flag.
    """
    from rpim_core_api.qa.checks import check_claims, check_sensitivity  # type: ignore[import]

    # Context that does NOT contain any of the numbers used in the claims traps.
    context = "قیمت پایه ۱۰۰ تومان"

    # 10 number-claims traps — numbers absent from context; mix Persian & western
    claims_traps: list[tuple[str, str]] = [
        ("قیمت ۵۰۰۰ تومان است", context),               # Persian ۵۰۰۰
        ("تخفیف ۳۰ درصدی برای خریداران", context),      # Persian ۳۰
        ("۱۵ محصول باقی مانده در انبار", context),       # Persian ۱۵
        ("فروش ۱۲۰۰۰ نسخه در بازار", context),          # Persian ۱۲۰۰۰
        ("۹۹ درصد رضایت مشتریان", context),              # Persian ۹۹
        ("price is 2500 rials", context),                 # western 2500
        ("warranty of 24 months included", context),      # western 24
        ("موجودی ۵۰ عدد موجود است", context),            # Persian ۵۰
        ("رشد ۴۵ درصدی در سال جاری", context),          # Persian ۴۵
        ("بازگشت سرمایه در 18 ماه", context),            # western 18
    ]

    # 10 sensitive traps — 2 per category; each must yield level=='block'
    sensitive_traps: list[str] = [
        # political (2) — keyword: انتخابات
        "در این انتخابات شرکت کنید",
        "نتایج انتخابات اعلام شد",
        # religious (2) — keyword: مذهبی / تحریم مذهبی
        "این برنامه با تحریم مذهبی روبرو شد",
        "تبلیغات مذهبی در رسانه‌ها رشد کرد",
        # ethnic (2) — keyword: قومیت
        "تبعیض بر اساس قومیت ممنوع است",
        "ساختار قومیتی جامعه پیچیده است",
        # gender (2) — keyword: جنسیتی
        "تبعیض جنسیتی در استخدام وجود دارد",
        "نابرابری جنسیتی در حقوق کارکنان",
        # health (2) — keyword: درمان قطعی
        "این محصول درمان قطعی دیابت است",
        "درمان قطعی همه بیماری‌ها با این روش",
    ]

    failures: list[str] = []

    for i, (text, ctx) in enumerate(claims_traps):
        flags = check_claims(text, ctx)
        if not flags:
            failures.append(
                f"claims_trap[{i}] yielded no flags — text={text!r}"
            )

    for i, text in enumerate(sensitive_traps):
        flags = check_sensitivity(text)
        if not flags:
            failures.append(
                f"sensitive_trap[{i}] yielded no flags — text={text!r}"
            )
        else:
            non_block = [f for f in flags if f.get("level") != "block"]
            if non_block:
                failures.append(
                    f"sensitive_trap[{i}] has non-block flags {non_block} — text={text!r}"
                )

    assert not failures, (
        f"Trap set: {len(failures)} of 20 samples failed:\n" + "\n".join(failures)
    )


# ===========================================================================
# 5. QA endpoint — POST /qa/check/{draft_id}
# ===========================================================================


def test_m5_qa_endpoint_requires_auth(client: TestClient):
    """POST /qa/check/<id> without Bearer token → 401."""
    resp = client.post("/qa/check/nonexistent-draft-id")
    assert resp.status_code == 401, (
        f"Expected 401 for unauthenticated QA check, got {resp.status_code}"
    )


def test_m5_qa_endpoint_404_other_tenant_draft(client: TestClient):
    """POST /qa/check/<id> using another tenant's draft_id → 404 (cross-tenant isolation).

    The owner-access assertion acts as a gate: it fails with a clear error when
    the route does not yet exist (404 from routing ≠ 200), so the isolation
    assertion is only reached once the route is implemented.
    """
    token_a = _register(
        client, "m5-qa-isol-a@test.com", "Passw0rd1!", "M5QAIsolA"
    )["access_token"]
    token_b = _register(
        client, "m5-qa-isol-b@test.com", "Passw0rd1!", "M5QAIsolB"
    )["access_token"]

    draft_id = _create_draft(client, token_a)

    # Gate: owner must get 200 — proves the route exists.
    owner_resp = client.post(f"/qa/check/{draft_id}", headers=_auth(token_a))
    assert owner_resp.status_code == 200, (
        f"Owner must get 200 from POST /qa/check/{draft_id} (route must exist), "
        f"got {owner_resp.status_code}: {owner_resp.text}"
    )

    # Cross-tenant isolation check.
    resp = client.post(f"/qa/check/{draft_id}", headers=_auth(token_b))
    assert resp.status_code == 404, (
        f"Tenant B accessing Tenant A's draft via /qa/check must get 404, "
        f"got {resp.status_code}: {resp.text}"
    )


def test_m5_qa_endpoint_returns_200_shape(client: TestClient):
    """POST /qa/check/<id> by the owner → 200 with 'flags' list and 'requires_human' bool."""
    token = _register(
        client, "m5-qa-shape@test.com", "Passw0rd1!", "M5QAShape"
    )["access_token"]
    draft_id = _create_draft(client, token)

    resp = client.post(f"/qa/check/{draft_id}", headers=_auth(token))
    assert resp.status_code == 200, (
        f"POST /qa/check/{draft_id} must return 200, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "flags" in body, f"'flags' missing from QA response: {body}"
    assert isinstance(body["flags"], list), f"'flags' must be a list: {body}"
    assert "requires_human" in body, f"'requires_human' missing from QA response: {body}"
    assert isinstance(body["requires_human"], bool), (
        f"'requires_human' must be bool: {body}"
    )


def test_m5_qa_requires_human_false_when_no_block_flags(client: TestClient):
    """requires_human must be False when no flag has level=='block'."""
    token = _register(
        client, "m5-qa-noblock@test.com", "Passw0rd1!", "M5QANoBlock"
    )["access_token"]
    # Provide a brain source so context numbers appear in draft, reducing claims flags.
    client.post(
        "/brain/sources",
        json={"title": "منبع", "kind": "upload", "text": "قیمت پایه ۱۰۰ تومان"},
        headers=_auth(token),
    )
    draft_id = _create_draft(client, token)

    resp = client.post(f"/qa/check/{draft_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    has_block = any(f.get("level") == "block" for f in body.get("flags", []))
    if not has_block:
        assert body["requires_human"] is False, (
            f"requires_human must be False when no block-level flags: {body}"
        )


def test_m5_qa_requires_human_true_when_sensitivity_in_draft(client: TestClient):
    """requires_human must be True when draft text contains a sensitivity keyword.

    The fake completer echoes the retrieved context verbatim into the draft
    text, so uploading a brain source with 'انتخابات' guarantees the draft
    text will contain that political keyword, triggering a block-level flag
    and making requires_human==True.
    """
    token = _register(
        client, "m5-qa-req-human@test.com", "Passw0rd1!", "M5QAReqHuman"
    )["access_token"]
    # Upload a source whose text will appear in the fake draft (political keyword).
    client.post(
        "/brain/sources",
        json={"title": "منبع سیاسی", "kind": "upload", "text": "کمپین انتخابات"},
        headers=_auth(token),
    )
    draft_id = _create_draft(client, token)

    resp = client.post(f"/qa/check/{draft_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requires_human"] is True, (
        f"requires_human must be True when draft contains political keyword 'انتخابات', "
        f"got: {body}"
    )


def test_m5_qa_flags_persisted_draft_still_accessible(client: TestClient):
    """After POST /qa/check/<id>, GET /content/drafts/<id> still returns 200.

    Verifies that persisting QA flags does not corrupt the draft row.
    The QA check assertion acts as a gate: fails when the route is missing.
    """
    token = _register(
        client, "m5-qa-persist@test.com", "Passw0rd1!", "M5QAPersist"
    )["access_token"]
    draft_id = _create_draft(client, token)

    # Gate: QA check must succeed before we verify draft persistence.
    qa_resp = client.post(f"/qa/check/{draft_id}", headers=_auth(token))
    assert qa_resp.status_code == 200, (
        f"POST /qa/check/{draft_id} must return 200 (route must exist), "
        f"got {qa_resp.status_code}: {qa_resp.text}"
    )

    get_resp = client.get(f"/content/drafts/{draft_id}", headers=_auth(token))
    assert get_resp.status_code == 200, (
        f"GET /content/drafts/{draft_id} after QA check must return 200, "
        f"got {get_resp.status_code}: {get_resp.text}"
    )


# ===========================================================================
# 6. Governance: status, silence, kill switch
# ===========================================================================


def test_m5_governance_status_requires_auth(client: TestClient):
    """GET /governance/status without Bearer token → 401."""
    resp = client.get("/governance/status")
    assert resp.status_code == 401, (
        f"Expected 401 for unauthenticated GET /governance/status, got {resp.status_code}"
    )


def test_m5_governance_status_initial(client: TestClient):
    """GET /governance/status with valid token → 200 {"silence": false, "kill": false}."""
    token = _register(
        client, "m5-gov-init@test.com", "Passw0rd1!", "M5GovInit"
    )["access_token"]
    resp = client.get("/governance/status", headers=_auth(token))
    assert resp.status_code == 200, (
        f"GET /governance/status must return 200, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "silence" in body, f"'silence' missing from governance status: {body}"
    assert "kill" in body, f"'kill' missing from governance status: {body}"
    assert body["silence"] is False, (
        f"Initial silence must be False, got: {body}"
    )
    assert body["kill"] is False, (
        f"Initial kill must be False, got: {body}"
    )


def test_m5_governance_silence_activates(client: TestClient):
    """POST /governance/silence with active=true → 200; status.silence becomes true."""
    token = _register(
        client, "m5-gov-sil-on@test.com", "Passw0rd1!", "M5GovSilOn"
    )["access_token"]
    resp = client.post(
        "/governance/silence",
        json={"active": True, "reason": "عزای عمومی"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, (
        f"POST /governance/silence must return 200, got {resp.status_code}: {resp.text}"
    )
    status = client.get("/governance/status", headers=_auth(token)).json()
    assert status["silence"] is True, (
        f"silence must be True after activation, got: {status}"
    )


def test_m5_governance_silence_releases(client: TestClient):
    """POST /governance/silence active=false → status.silence returns to false.

    Blueprint rule 7: manual-only resume — no auto-resume anywhere.
    """
    token = _register(
        client, "m5-gov-sil-off@test.com", "Passw0rd1!", "M5GovSilOff"
    )["access_token"]
    # Activate
    client.post(
        "/governance/silence",
        json={"active": True, "reason": "عزای عمومی"},
        headers=_auth(token),
    )
    # Manual release
    resp = client.post(
        "/governance/silence",
        json={"active": False, "reason": "پایان عزا"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    status = client.get("/governance/status", headers=_auth(token)).json()
    assert status["silence"] is False, (
        f"silence must be False after manual release, got: {status}"
    )


def test_m5_governance_kill_wrong_token_rejected(client: TestClient):
    """POST /governance/kill with wrong X-Internal-Token → 401."""
    token = _register(
        client, "m5-gov-kill-bad@test.com", "Passw0rd1!", "M5GovKillBad"
    )["access_token"]
    resp = client.post(
        "/governance/kill",
        json={"active": True, "reason": "اضطرار"},
        headers={**_auth(token), "X-Internal-Token": "this-is-the-wrong-token"},
    )
    assert resp.status_code == 401, (
        f"Wrong X-Internal-Token must return 401, got {resp.status_code}: {resp.text}"
    )


def test_m5_governance_kill_missing_token_rejected(client: TestClient):
    """POST /governance/kill with no X-Internal-Token header → 401."""
    token = _register(
        client, "m5-gov-kill-notoken@test.com", "Passw0rd1!", "M5GovKillNoToken"
    )["access_token"]
    resp = client.post(
        "/governance/kill",
        json={"active": True, "reason": "اضطرار"},
        headers=_auth(token),  # no X-Internal-Token
    )
    assert resp.status_code == 401, (
        f"Missing X-Internal-Token must return 401, got {resp.status_code}: {resp.text}"
    )


def test_m5_governance_kill_switch_affects_all_tenants(client: TestClient):
    """POST /governance/kill with correct X-Internal-Token → 200;
    EVERY tenant's GET /governance/status shows kill==true (global, not per-tenant).

    Blueprint rule 7: kill switch stops all publish queues in <5s.
    """
    token_a = _register(
        client, "m5-kill-a@test.com", "Passw0rd1!", "M5KillA"
    )["access_token"]
    token_b = _register(
        client, "m5-kill-b@test.com", "Passw0rd1!", "M5KillB"
    )["access_token"]

    # Activate the global kill switch using the correct internal token
    resp = client.post(
        "/governance/kill",
        json={"active": True, "reason": "اضطرار سراسری"},
        headers={**_auth(token_a), "X-Internal-Token": _INTERNAL_TOKEN},
    )
    assert resp.status_code == 200, (
        f"POST /governance/kill with correct token must return 200, "
        f"got {resp.status_code}: {resp.text}"
    )

    # Both tenants must see kill==true (global effect)
    status_a = client.get("/governance/status", headers=_auth(token_a)).json()
    status_b = client.get("/governance/status", headers=_auth(token_b)).json()
    assert status_a.get("kill") is True, (
        f"Tenant A must see kill==true after kill switch, got: {status_a}"
    )
    assert status_b.get("kill") is True, (
        f"Tenant B must see kill==true after kill switch (global), got: {status_b}"
    )

    # Release the kill switch so this test's DB state is clean
    client.post(
        "/governance/kill",
        json={"active": False, "reason": "پایان اضطرار"},
        headers={**_auth(token_a), "X-Internal-Token": _INTERNAL_TOKEN},
    )


def test_m5_governance_kill_releases(client: TestClient):
    """POST /governance/kill active=false releases the kill switch → status.kill==false."""
    token = _register(
        client, "m5-kill-rel@test.com", "Passw0rd1!", "M5KillRel"
    )["access_token"]
    # Activate
    client.post(
        "/governance/kill",
        json={"active": True, "reason": "اضطرار"},
        headers={**_auth(token), "X-Internal-Token": _INTERNAL_TOKEN},
    )
    # Release
    resp = client.post(
        "/governance/kill",
        json={"active": False, "reason": "پایان اضطرار"},
        headers={**_auth(token), "X-Internal-Token": _INTERNAL_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    status = client.get("/governance/status", headers=_auth(token)).json()
    assert status["kill"] is False, (
        f"kill must be False after release, got: {status}"
    )


# ===========================================================================
# 7. Cross-tenant isolation — silence is per-tenant (CLAUDE.md rule 6)
# ===========================================================================


def test_m5_qa_cross_tenant_isolation(client: TestClient):
    """Tenant A's silence must NOT leak to Tenant B.

    CLAUDE.md rule 6: every query scoped by tenant_id; every new table ships
    with a test proving cross-tenant isolation.

    Governance state for silence is per-tenant; kill switch is intentionally
    global (separate contract, tested above).
    """
    token_a = _register(
        client, "m5-iso-a@test.com", "Passw0rd1!", "M5IsoA"
    )["access_token"]
    token_b = _register(
        client, "m5-iso-b@test.com", "Passw0rd1!", "M5IsoB"
    )["access_token"]

    # Activate silence for Tenant A only
    resp = client.post(
        "/governance/silence",
        json={"active": True, "reason": "عزای عمومی"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 200, resp.text

    # Tenant A must see silence==true
    status_a = client.get("/governance/status", headers=_auth(token_a)).json()
    assert status_a["silence"] is True, (
        f"Tenant A must see silence==true, got: {status_a}"
    )

    # Tenant B must NOT see Tenant A's silence
    status_b = client.get("/governance/status", headers=_auth(token_b)).json()
    assert status_b["silence"] is False, (
        f"Tenant B must NOT inherit Tenant A's silence (cross-tenant isolation), "
        f"got: {status_b}"
    )
