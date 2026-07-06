"""
M12 acceptance tests — Image publish: M8 renderer connected to M7 pipeline.

Routes under test:
  POST /publish/jobs       (gains optional 'image' field)
  GET  /publish/jobs       (entries gain 'image_spec')
  POST /publish/dispatch   (routes image jobs via send_photo)

New module under test:
  rpim_core_api.publisher.renderer_client  (render_for_job, fake/remote seam)

Channel seam extension under test:
  rpim_core_api.publisher.channels.send_photo  (kind='photo', image_size pin)

Env PUBLISH_MODE=fake, RENDER_FETCH_MODE=fake, EMBED_MODE=fake, COMPLETE_MODE=fake
are set at module level BEFORE any import of rpim_core_api.* — same pattern as M7.
INTERNAL_TOKEN is generated once per run and shared via setdefault (whichever module
imports first wins).

rpim_core_api.publisher.channels is imported at module level because it exists
post-M7 and its _OUTBOX / _FAIL_NEXT lists are needed for seam control.

rpim_core_api.publisher.renderer_client is imported INSIDE individual tests because
the module does not exist yet — ModuleNotFoundError is the correct pre-M12
failure mode for those tests (not a collection error for the whole file).

Expected failure modes before M12 is implemented:
  - Contract 1 (API image field): AssertionError — 'image_spec' missing from
    response, or status 201 instead of 422 for unknown template/size.
  - Contract 2 (renderer_client): ModuleNotFoundError — module does not exist.
  - Contract 3 (send_photo / dispatch): AttributeError — 'send_photo' not in
    channels; or AssertionError — dispatch routes image jobs through text path
    (kind != 'photo').

All tests named test_m12_<criterion>.
"""

from __future__ import annotations

import os
import secrets

# Must be set BEFORE any import of rpim_core_api.* (same pattern as M7/M5/M6).
# RENDER_FETCH_MODE=fake routes all renderer calls through the in-process seam.
os.environ["PUBLISH_MODE"] = "fake"
os.environ["RENDER_FETCH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

# setdefault: whichever module imports first (test_m7_publish.py or this file)
# wins; both processes share the same INTERNAL_TOKEN.
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# channels is imported at module level (exists post-M7); send_photo raises
# AttributeError until it is added — expected failure for M12 pre-implementation.
# renderer_client is imported inside individual tests (doesn't exist yet).
# ---------------------------------------------------------------------------
import rpim_core_api.publisher.channels as _channels  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}

_VALID_TEMPLATES = ("announce", "quote", "product")
_VALID_SIZES = ("square", "story", "wide")

# ---------------------------------------------------------------------------
# Helpers — exact M7 pattern
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _setup_tenant(client: TestClient, email: str, password: str, tenant_name: str) -> str:
    return _register(client, email, password, tenant_name)["access_token"]


def _create_draft(client: TestClient, token: str) -> str:
    resp = client.post(
        "/content/drafts",
        json={"brief": _BRIEF},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"draft create failed: {resp.text}"
    return resp.json()["draft_id"]


def _approve_draft(client: TestClient, token: str, draft_id: str) -> None:
    resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert resp.status_code == 200, f"approve failed: {resp.text}"


def _create_approved_draft(client: TestClient, token: str) -> str:
    draft_id = _create_draft(client, token)
    _approve_draft(client, token, draft_id)
    return draft_id


def _create_job(
    client: TestClient,
    token: str,
    draft_id: str,
    channel: str = "telegram",
    chat_id: str = "12345",
    campaign_code: str = "camp_test_001",
    scheduled_at: str | None = None,
    image: dict | None = None,
):
    payload: dict = {
        "draft_id": draft_id,
        "channel": channel,
        "chat_id": chat_id,
        "campaign_code": campaign_code,
    }
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at
    if image is not None:
        payload["image"] = image
    return client.post("/publish/jobs", json=payload, headers=_auth(token))


def _clear_outbox() -> None:
    """Clear fake channel seam state between test cases."""
    _channels._OUTBOX.clear()
    _channels._FAIL_NEXT.clear()


def _internal_header() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


# ===========================================================================
# Contract 1 — POST /publish/jobs gains optional 'image' field
# ===========================================================================


def test_m12_create_job_with_image_spec_201(client: TestClient):
    """POST /publish/jobs with valid image spec → 201, response contains image_spec dict."""
    _clear_outbox()
    token = _setup_tenant(client, "m12-img201@test.com", "pw123456", "M12Img201")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(
        client, token, draft_id,
        image={"template": "announce", "size": "square"},
    )
    assert resp.status_code == 201, (
        f"expected 201 for image job creation, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "image_spec" in body, (
        f"'image_spec' must be present in POST /publish/jobs response: {body}"
    )
    assert body["image_spec"] == {"template": "announce", "size": "square"}, (
        f"image_spec must mirror the request dict, got: {body.get('image_spec')}"
    )


def test_m12_create_job_image_unknown_template_422(client: TestClient):
    """POST /publish/jobs with unknown template value → 422."""
    _clear_outbox()
    token = _setup_tenant(client, "m12-tmpl422@test.com", "pw123456", "M12Tmpl422")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(
        client, token, draft_id,
        image={"template": "banner", "size": "square"},
    )
    assert resp.status_code == 422, (
        f"unknown template 'banner' must return 422, got {resp.status_code}: {resp.text}"
    )


def test_m12_create_job_image_unknown_size_422(client: TestClient):
    """POST /publish/jobs with unknown size value → 422."""
    _clear_outbox()
    token = _setup_tenant(client, "m12-size422@test.com", "pw123456", "M12Size422")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(
        client, token, draft_id,
        image={"template": "announce", "size": "ultra"},
    )
    assert resp.status_code == 422, (
        f"unknown size 'ultra' must return 422, got {resp.status_code}: {resp.text}"
    )


def test_m12_create_job_without_image_has_null_image_spec(client: TestClient):
    """POST /publish/jobs without image field → 201, image_spec is null (M7/M9 unchanged)."""
    _clear_outbox()
    token = _setup_tenant(client, "m12-noimg@test.com", "pw123456", "M12NoImg")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(client, token, draft_id)
    assert resp.status_code == 201, (
        f"text-only job must still return 201, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "image_spec" in body, (
        f"'image_spec' must be present in response even when no image provided: {body}"
    )
    assert body["image_spec"] is None, (
        f"image_spec must be null when no image field sent, got: {body.get('image_spec')}"
    )


def test_m12_list_jobs_includes_image_spec(client: TestClient):
    """GET /publish/jobs entries include image_spec field (dict for image jobs, null otherwise)."""
    _clear_outbox()
    token = _setup_tenant(client, "m12-listimg@test.com", "pw123456", "M12ListImg")
    draft_id = _create_approved_draft(client, token)

    job_resp = _create_job(
        client, token, draft_id,
        image={"template": "quote", "size": "story"},
        campaign_code="camp_list_img",
    )
    assert job_resp.status_code == 201, f"image job creation failed: {job_resp.text}"
    job_id = job_resp.json()["job_id"]

    list_resp = client.get("/publish/jobs", headers=_auth(token))
    assert list_resp.status_code == 200
    jobs = list_resp.json()["jobs"]
    target = next((j for j in jobs if j["job_id"] == job_id), None)
    assert target is not None, f"job {job_id} not found in GET /publish/jobs: {jobs}"
    assert "image_spec" in target, (
        f"'image_spec' must appear in GET /publish/jobs entries: {target}"
    )
    assert target["image_spec"] == {"template": "quote", "size": "story"}, (
        f"image_spec in list must match creation value, got: {target.get('image_spec')}"
    )


def test_m12_create_job_all_valid_templates_and_sizes(client: TestClient):
    """Every valid template × size combination is accepted and returned in image_spec."""
    _clear_outbox()
    token = _setup_tenant(client, "m12-combos@test.com", "pw123456", "M12Combos")

    for template in _VALID_TEMPLATES:
        for size in _VALID_SIZES:
            draft_id = _create_approved_draft(client, token)
            resp = _create_job(
                client, token, draft_id,
                image={"template": template, "size": size},
                campaign_code=f"camp_{template}_{size}",
            )
            assert resp.status_code == 201, (
                f"template={template!r} size={size!r} must return 201, "
                f"got {resp.status_code}: {resp.text}"
            )
            body = resp.json()
            assert body.get("image_spec") == {"template": template, "size": size}, (
                f"image_spec must equal the sent spec for template={template!r} "
                f"size={size!r}, got: {body.get('image_spec')}"
            )


# ===========================================================================
# Contract 2 — rpim_core_api.publisher.renderer_client
# ===========================================================================


def test_m12_renderer_client_fake_returns_png_bytes():
    """RENDER_FETCH_MODE=fake: render_for_job returns bytes with PNG magic prefix."""
    import rpim_core_api.publisher.renderer_client as _renderer  # type: ignore[import]

    class _FakeJob:
        image_spec = {"template": "announce", "size": "square"}
        text = "متن اعلان تستی"

    result = _renderer.render_for_job(_FakeJob())
    assert isinstance(result, bytes), (
        f"render_for_job must return bytes in fake mode, got {type(result)}"
    )
    # PNG magic: \x89PNG\r\n\x1a\n
    assert result[:4] == b"\x89PNG", (
        f"render_for_job fake mode must return PNG-magic-prefixed bytes "
        f"(\\x89PNG...), got: {result[:8]!r}"
    )
    assert len(result) > 8, (
        f"render_for_job must return more than just the magic header, "
        f"got {len(result)} bytes"
    )


def test_m12_renderer_client_fake_deterministic():
    """Same job (same image_spec + text) → identical bytes every call."""
    import rpim_core_api.publisher.renderer_client as _renderer  # type: ignore[import]

    class _FakeJob:
        image_spec = {"template": "quote", "size": "story"}
        text = "همان متن برای هر دو فراخوانی"

    result1 = _renderer.render_for_job(_FakeJob())
    result2 = _renderer.render_for_job(_FakeJob())
    assert result1 == result2, (
        f"render_for_job must be deterministic: same job → same bytes; "
        f"first={result1[:16]!r}, second={result2[:16]!r}"
    )


def test_m12_renderer_client_fake_different_template_different_bytes():
    """Different template in image_spec → different bytes (prevents template mix-up)."""
    import rpim_core_api.publisher.renderer_client as _renderer  # type: ignore[import]

    class _AnnounceJob:
        image_spec = {"template": "announce", "size": "square"}
        text = "متن یکسان برای هر دو"

    class _QuoteJob:
        image_spec = {"template": "quote", "size": "square"}
        text = "متن یکسان برای هر دو"

    result_announce = _renderer.render_for_job(_AnnounceJob())
    result_quote = _renderer.render_for_job(_QuoteJob())
    assert result_announce != result_quote, (
        "render_for_job must produce different bytes for different templates "
        "(announce vs quote); got identical output"
    )


def test_m12_renderer_client_remote_no_url_raises():
    """RENDER_FETCH_MODE=remote without RENDERER_URL → RuntimeError naming 'RENDERER_URL'."""
    import rpim_core_api.publisher.renderer_client as _renderer  # type: ignore[import]

    original_mode = os.environ.get("RENDER_FETCH_MODE")
    original_url = os.environ.get("RENDERER_URL")
    try:
        os.environ["RENDER_FETCH_MODE"] = "remote"
        os.environ.pop("RENDERER_URL", None)

        class _FakeJob:
            image_spec = {"template": "announce", "size": "square"}
            text = "test"

        raised = False
        error_message = ""
        try:
            _renderer.render_for_job(_FakeJob())
        except RuntimeError as exc:
            raised = True
            error_message = str(exc)

        assert raised, (
            "render_for_job must raise RuntimeError when "
            "RENDER_FETCH_MODE=remote and RENDERER_URL is unset"
        )
        assert "RENDERER_URL" in error_message, (
            f"RuntimeError message must name 'RENDERER_URL' (rule 4: name the var, "
            f"not a value), got: {error_message!r}"
        )
    finally:
        # Restore environment so subsequent tests are unaffected
        if original_mode is not None:
            os.environ["RENDER_FETCH_MODE"] = original_mode
        else:
            os.environ.pop("RENDER_FETCH_MODE", None)
        if original_url is not None:
            os.environ["RENDERER_URL"] = original_url


# ===========================================================================
# Contract 3 — channels.send_photo + dispatch routing
# ===========================================================================


def test_m12_send_photo_fake_seam_appended_to_outbox():
    """channels.send_photo (fake mode) appends to _OUTBOX with kind='photo' and image_size."""
    _clear_outbox()
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    _channels.send_photo(
        channel="telegram",
        chat_id="99001",
        caption="عنوان عکس",
        image_png=image_bytes,
        job_id="job_photo_001",
    )

    assert len(_channels._OUTBOX) == 1, (
        f"_OUTBOX must have 1 entry after send_photo, got: {_channels._OUTBOX}"
    )
    entry = _channels._OUTBOX[0]
    assert entry.get("kind") == "photo", (
        f"_OUTBOX entry 'kind' must be 'photo', got: {entry.get('kind')!r}"
    )
    assert "image_size" in entry, (
        f"_OUTBOX entry must have 'image_size' key: {entry}"
    )
    assert entry["image_size"] == len(image_bytes), (
        f"image_size must equal len(image_png)={len(image_bytes)}, "
        f"got: {entry.get('image_size')}"
    )
    assert entry.get("job_id") == "job_photo_001", (
        f"job_id mismatch in _OUTBOX: {entry}"
    )
    assert entry.get("caption") == "عنوان عکس", (
        f"caption mismatch in _OUTBOX: {entry}"
    )
    assert entry.get("channel") == "telegram", (
        f"channel mismatch in _OUTBOX: {entry}"
    )
    assert entry.get("chat_id") == "99001", (
        f"chat_id mismatch in _OUTBOX: {entry}"
    )


def test_m12_send_photo_fail_next_applies_one_shot():
    """_FAIL_NEXT applies to send_photo with the same one-shot semantics as send().

    Injecting channel name → ChannelSendError on first call, entry consumed,
    _OUTBOX empty; second call succeeds.
    """
    _clear_outbox()
    _channels._FAIL_NEXT.append("telegram")
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    raised = False
    try:
        _channels.send_photo(
            channel="telegram",
            chat_id="99002",
            caption="fail test",
            image_png=image_bytes,
            job_id="job_photo_002",
        )
    except _channels.ChannelSendError:
        raised = True

    assert raised, (
        "send_photo must raise ChannelSendError when _FAIL_NEXT contains the channel"
    )
    assert "telegram" not in _channels._FAIL_NEXT, (
        "_FAIL_NEXT entry must be consumed after one failure (one-shot semantics)"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty after failed send_photo, got: {_channels._OUTBOX}"
    )

    # Second call (no injected failure) must succeed
    _channels.send_photo(
        channel="telegram",
        chat_id="99002",
        caption="fail test",
        image_png=image_bytes,
        job_id="job_photo_002",
    )
    assert len(_channels._OUTBOX) == 1, (
        f"second send_photo must succeed, _OUTBOX must have 1 entry, "
        f"got: {_channels._OUTBOX}"
    )
    assert _channels._OUTBOX[0].get("kind") == "photo", (
        f"successful retry must still produce kind='photo': {_channels._OUTBOX[0]}"
    )


def test_m12_dispatch_image_job_uses_send_photo(client: TestClient):
    """e2e: approved draft + image job → dispatch → _OUTBOX has kind='photo'.

    Pinned assertions (constitution rule 2 & blueprint §6.4):
      - _OUTBOX entry kind == 'photo'
      - image_size > 8 (more than PNG magic header alone)
      - caption == the draft's generated text (not empty)
      - job status == 'sent' after dispatch
    """
    _clear_outbox()
    token = _setup_tenant(client, "m12-dispimg@test.com", "pw123456", "M12DispImg")
    draft_id = _create_approved_draft(client, token)

    job_resp = _create_job(
        client, token, draft_id,
        channel="telegram",
        chat_id="98001",
        campaign_code="camp_img_dispatch",
        image={"template": "announce", "size": "square"},
    )
    assert job_resp.status_code == 201, f"image job creation failed: {job_resp.text}"
    job_id = job_resp.json()["job_id"]

    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch_resp.status_code == 200, (
        f"dispatch must return 200, got {dispatch_resp.status_code}: {dispatch_resp.text}"
    )
    body = dispatch_resp.json()
    assert body["sent"] >= 1, f"dispatch must report sent>=1 for image job, got: {body}"

    # Exactly one _OUTBOX entry for this job
    job_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(job_entries) == 1, (
        f"_OUTBOX must have exactly 1 entry for job {job_id}, "
        f"got: {_channels._OUTBOX}"
    )
    entry = job_entries[0]
    assert entry.get("kind") == "photo", (
        f"dispatch must route image jobs through send_photo (kind='photo'), "
        f"got kind: {entry.get('kind')!r}"
    )
    assert entry.get("image_size", 0) > 8, (
        f"image_size must be > 8 bytes (PNG magic + payload), "
        f"got: {entry.get('image_size')}"
    )
    assert entry.get("caption"), (
        f"caption must be the draft's text (non-empty), got: {entry.get('caption')!r}"
    )

    # Job must be 'sent'
    jobs_resp = client.get("/publish/jobs", headers=_auth(token))
    assert jobs_resp.status_code == 200
    jobs_data = jobs_resp.json()["jobs"]
    target = next((j for j in jobs_data if j["job_id"] == job_id), None)
    assert target is not None, f"job {job_id} not found after dispatch"
    assert target["status"] == "sent", (
        f"job status must be 'sent' after successful photo dispatch, "
        f"got: {target.get('status')}"
    )


def test_m12_dispatch_text_job_unchanged(client: TestClient):
    """Job WITHOUT image_spec dispatches via text send() exactly as today (M7 unchanged).

    Regression guard: text-only jobs must not be routed through send_photo.
    Also verifies that GET /publish/jobs includes image_spec: null for text jobs
    (migration 0009 must add the column with a nullable default).
    """
    _clear_outbox()
    token = _setup_tenant(client, "m12-textjob@test.com", "pw123456", "M12TextJob")
    draft_id = _create_approved_draft(client, token)

    job_resp = _create_job(client, token, draft_id, channel="telegram", chat_id="98002")
    assert job_resp.status_code == 201, f"text job creation failed: {job_resp.text}"
    job_id = job_resp.json()["job_id"]

    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch_resp.status_code == 200
    body = dispatch_resp.json()
    assert body["sent"] >= 1, f"text job must still dispatch successfully, got: {body}"

    job_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(job_entries) == 1, (
        f"_OUTBOX must have 1 entry for text job, got: {_channels._OUTBOX}"
    )
    entry = job_entries[0]
    assert entry.get("kind") != "photo", (
        f"text job must NOT be dispatched through send_photo path, "
        f"got kind={entry.get('kind')!r}"
    )
    assert "text" in entry, (
        f"text job _OUTBOX entry must carry 'text' key: {entry}"
    )

    # GET /publish/jobs must include image_spec: null for text-only jobs
    list_resp = client.get("/publish/jobs", headers=_auth(token))
    assert list_resp.status_code == 200
    jobs_data = list_resp.json()["jobs"]
    target = next((j for j in jobs_data if j["job_id"] == job_id), None)
    assert target is not None, f"job {job_id} not found in list"
    assert "image_spec" in target, (
        f"GET /publish/jobs entry must include 'image_spec' field "
        f"(null for text-only jobs): {target}"
    )
    assert target["image_spec"] is None, (
        f"image_spec must be null for text-only job, got: {target.get('image_spec')}"
    )


def test_m12_silence_blocks_before_render(client: TestClient):
    """Silence flag stops dispatch BEFORE render_for_job is invoked.

    Constitution rule 2: the silence check lives INSIDE the publisher and
    precedes EVERY publish step — render must never run for a halted tenant.

    Pin: monkeypatching renderer_client.render_for_job with a recorder that
    raises AssertionError if called under silence.
    """
    _clear_outbox()
    token = _setup_tenant(client, "m12-silrend@test.com", "pw123456", "M12SilRend")
    draft_id = _create_approved_draft(client, token)

    job_resp = _create_job(
        client, token, draft_id,
        channel="telegram",
        chat_id="98003",
        image={"template": "announce", "size": "square"},
    )
    assert job_resp.status_code == 201, f"image job creation failed: {job_resp.text}"
    job_id = job_resp.json()["job_id"]

    # Activate tenant silence
    sil_resp = client.post(
        "/governance/silence",
        json={"active": True, "reason": "سکوت آزمایشی"},
        headers=_auth(token),
    )
    assert sil_resp.status_code == 200, f"silence activate failed: {sil_resp.text}"

    # Import renderer_client (fails here pre-M12; after M12, monkeypatch the function)
    import rpim_core_api.publisher.renderer_client as _renderer  # type: ignore[import]

    render_calls: list = []

    def _recorder(job):  # type: ignore[no-untyped-def]
        render_calls.append(job)
        raise AssertionError(
            "render_for_job must NOT be called when silence flag is active "
            "(constitution rule 2)"
        )

    original_render = _renderer.render_for_job
    _renderer.render_for_job = _recorder
    try:
        dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
        assert dispatch_resp.status_code == 200
        disp_body = dispatch_resp.json()
        assert disp_body["blocked"] >= 1, (
            f"dispatch under silence must return blocked>=1, got: {disp_body}"
        )
        assert _channels._OUTBOX == [], (
            f"_OUTBOX must be empty when silence is active, got: {_channels._OUTBOX}"
        )
        assert render_calls == [], (
            f"render_for_job must NOT have been called under silence; "
            f"was called {len(render_calls)} time(s)"
        )
        # Job must remain 'queued'
        jobs_resp = client.get("/publish/jobs", headers=_auth(token))
        jobs_data = jobs_resp.json()["jobs"]
        target = next((j for j in jobs_data if j["job_id"] == job_id), None)
        assert target is not None, f"job {job_id} must still exist after blocked dispatch"
        assert target["status"] == "queued", (
            f"job must remain 'queued' after silence-blocked dispatch, "
            f"got: {target.get('status')}"
        )
    finally:
        _renderer.render_for_job = original_render
        client.post(
            "/governance/silence",
            json={"active": False, "reason": "پایان سکوت"},
            headers=_auth(token),
        )


def test_m12_photo_transient_failure_retry(client: TestClient):
    """_FAIL_NEXT one-shot → failed>=1, job queued, attempts==1, _OUTBOX empty.
    Second dispatch → exactly 1 photo entry, no double-send.

    Blueprint acceptance (Persian): «قطع تونل وسط انتشار → نه گم شدن، نه دوباره‌فرستادن»
    Same guarantee as M7 transient-failure test, extended to photo send path.
    """
    _clear_outbox()
    token = _setup_tenant(client, "m12-photoretry@test.com", "pw123456", "M12PhotoRetry")
    draft_id = _create_approved_draft(client, token)

    job_resp = _create_job(
        client, token, draft_id,
        channel="telegram",
        chat_id="98004",
        campaign_code="camp_photo_retry",
        image={"template": "product", "size": "wide"},
    )
    assert job_resp.status_code == 201, f"image job creation failed: {job_resp.text}"
    job_id = job_resp.json()["job_id"]

    # Inject a one-shot transient failure for the telegram photo send
    _channels._FAIL_NEXT.append("telegram")

    # First dispatch — transient failure
    r1 = client.post("/publish/dispatch", headers=_internal_header())
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["failed"] >= 1, (
        f"first dispatch with injected failure must report failed>=1, got: {body1}"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty after failed photo send, got: {_channels._OUTBOX}"
    )

    # Job must still be queued with attempts==1
    jobs_resp = client.get("/publish/jobs", headers=_auth(token))
    jobs_data = jobs_resp.json()["jobs"]
    target = next((j for j in jobs_data if j["job_id"] == job_id), None)
    assert target is not None, (
        f"job {job_id} must not be lost after transient photo failure"
    )
    assert target["status"] == "queued", (
        f"job must remain 'queued' after transient photo failure, "
        f"got: {target.get('status')}"
    )
    assert target.get("attempts") == 1, (
        f"attempts must be 1 after first failed dispatch, "
        f"got: {target.get('attempts')}"
    )

    # Second dispatch — no injected error → sends exactly once
    r2 = client.post("/publish/dispatch", headers=_internal_header())
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["sent"] >= 1, (
        f"second dispatch must send after failure cleared, got: {body2}"
    )
    job_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(job_entries) == 1, (
        f"after retry, _OUTBOX must have exactly 1 entry (no double-send), "
        f"got {len(job_entries)}: {_channels._OUTBOX}"
    )
    assert job_entries[0].get("kind") == "photo", (
        f"retry must still dispatch through send_photo, "
        f"got kind: {job_entries[0].get('kind')!r}"
    )


def test_m12_cross_tenant_image_job_isolation(client: TestClient):
    """Tenant B cannot create an image job for Tenant A's draft → 404.

    Constitution rule 6: tenant isolation is absolute; every new table ships
    with a cross-tenant isolation test. The image_spec field must not weaken
    the draft-ownership check.
    """
    _clear_outbox()
    token_a = _setup_tenant(client, "m12-xta@test.com", "pw123456", "M12XTenantA")
    token_b = _setup_tenant(client, "m12-xtb@test.com", "pw123456", "M12XTenantB")

    draft_id_a = _create_approved_draft(client, token_a)

    # Verify Tenant A's own image job works (checks image_spec in response)
    own_resp = _create_job(
        client, token_a, draft_id_a,
        image={"template": "announce", "size": "square"},
        campaign_code="camp_a_own",
    )
    assert own_resp.status_code == 201, (
        f"Tenant A's own image job must return 201, "
        f"got {own_resp.status_code}: {own_resp.text}"
    )
    own_body = own_resp.json()
    assert own_body.get("image_spec") == {"template": "announce", "size": "square"}, (
        f"Tenant A's image_spec must be returned in response, "
        f"got: {own_body.get('image_spec')}"
    )

    # Tenant B cannot create an image job for Tenant A's draft
    resp = _create_job(
        client, token_b, draft_id_a,
        image={"template": "announce", "size": "square"},
        campaign_code="camp_b_steal",
    )
    assert resp.status_code == 404, (
        f"Tenant B must get 404 when creating image job for Tenant A's draft "
        f"(constitution rule 6), got {resp.status_code}: {resp.text}"
    )
