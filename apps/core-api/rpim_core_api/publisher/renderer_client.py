"""Fetch rendered assets for image publish jobs.

RENDER_FETCH_MODE=fake (tests/CI) returns deterministic PNG-magic bytes so
retries stay byte-identical; remote mode calls the us-leg renderer over the
tunnel. Remote failures surface as ChannelSendError, so the engine treats a
dropped tunnel mid-render exactly like a dropped send: job stays queued.
"""

import base64
import hashlib
import os

import httpx

from rpim_core_api.models import PublishJob
from rpim_core_api.publisher.channels import ChannelSendError


def render_for_job(job: PublishJob) -> bytes:
    mode = os.environ.get("RENDER_FETCH_MODE", "fake")
    spec = job.image_spec or {}
    if mode == "fake":
        seed = f"{spec.get('template')}:{spec.get('size')}:{job.text}"
        return b"\x89PNG\r\n\x1a\n" + hashlib.sha256(seed.encode("utf-8")).digest()

    base_url = os.environ.get("RENDERER_URL", "")
    if not base_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("RENDER_FETCH_MODE=remote requires env var RENDERER_URL")
    internal = os.environ.get("INTERNAL_TOKEN", "")
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/render",
            json={
                "template": spec.get("template"),
                "size": spec.get("size"),
                "tenant_id": job.tenant_id,
                # Slice A: the approved post text doubles as the poster title;
                # brief-driven title/body/cta fields are a queued follow-up.
                "text": {"title": (job.text or "-")[:300], "body": "", "cta": ""},
            },
            headers={"X-Internal-Token": internal},
            timeout=30,
        )
        response.raise_for_status()
        return base64.b64decode(response.json()["image_b64"])
    except httpx.HTTPError as exc:
        # Transient like a dropped send: the job stays queued and retries.
        raise ChannelSendError(f"renderer fetch failed: {type(exc).__name__}") from exc
