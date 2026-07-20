"""Media-asset service (M21, ADR 0039) — generation, storage, dedupe.

Bytes never touch the DB: they land under MEDIA_STORAGE_DIR (a container
volume) addressed by sha256, and media_assets rows carry metadata only.
IMAGE_MODE=fake (tests/CI) produces deterministic local bytes; remote calls
the us-leg gateway /image with request_id = the PRE-CREATED asset id, so a
network-level duplicate of the same attempt can never double-charge
(rule 8) while a fresh attempt is always a fresh idempotency key."""

import base64
import hashlib
import os
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.models import MediaAsset, VisualPrompt


class MediaGenerationError(Exception):
    """Transient generation failure — surface as 503, asset row not kept."""


def _storage_dir() -> Path:
    root = Path(os.environ.get("MEDIA_STORAGE_DIR", "media_store"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_alt_text(subject: str) -> str:
    """Deterministic Persian SEO alt (design §3.2) — the subject verbatim so
    search engines index the product name; capped to the column budget."""
    subject = " ".join(subject.split())
    return f"تصویر تبلیغاتی: {subject}"[:300]


def _generate_bytes(prompt_text: str, tenant_id: str, request_id: str) -> tuple[bytes, dict]:
    mode = os.environ.get("IMAGE_MODE", "fake")
    if mode == "fake":
        seed = hashlib.sha256(prompt_text.encode()).hexdigest()
        return f"PNG-FAKE:{seed}".encode(), {
            "provider": "fake",
            "model": "echo-img",
            "cost_usd": 0.0,
        }
    gateway = os.environ.get("GATEWAY_URL", "")
    if not gateway:
        # Name the env var, never a value (rule 4).
        raise MediaGenerationError("IMAGE_MODE=remote requires env var GATEWAY_URL")
    response = httpx.post(
        f"{gateway.rstrip('/')}/image",
        json={"prompt": prompt_text, "tenant_id": tenant_id, "request_id": request_id},
        headers={"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")},
        timeout=180,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("image_b64"):
        # Cached receipt without bytes (gateway replay) and no local file —
        # this attempt cannot complete; the caller retries with a fresh id.
        raise MediaGenerationError("gateway returned a receipt without image bytes")
    return base64.b64decode(body["image_b64"]), {
        "provider": body.get("provider", ""),
        "model": body.get("model", ""),
        "cost_usd": float(body.get("cost_usd", 0.0)),
    }


def generate_for_prompt(
    session: Session, tenant_id: str, prompt: VisualPrompt
) -> tuple[MediaAsset, bool]:
    """Execute a visual prompt into a stored asset. Returns (asset, created).
    Dedupe: same tenant + same sha256 → the existing row (rule 8)."""
    import uuid  # noqa: PLC0415

    asset_id = uuid.uuid4().hex
    try:
        raw, meta = _generate_bytes(prompt.prompt_text, tenant_id, request_id=asset_id)
    except httpx.HTTPError as exc:
        raise MediaGenerationError("image gateway unavailable — try again shortly") from exc

    sha256 = hashlib.sha256(raw).hexdigest()
    existing = session.scalar(
        select(MediaAsset).where(
            MediaAsset.tenant_id == tenant_id,  # rule 6
            MediaAsset.sha256 == sha256,
        )
    )
    if existing is not None:
        return existing, False

    subject = str((prompt.brief or {}).get("subject", "")).strip() or "محتوای برند"
    tenant_dir = _storage_dir() / tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    path = tenant_dir / f"{sha256}.png"
    path.write_bytes(raw)

    asset = MediaAsset(
        id=asset_id,
        tenant_id=tenant_id,
        kind="generated",
        prompt_id=prompt.id,
        provider=meta["provider"],
        model=meta["model"],
        prompt_text=prompt.prompt_text,
        alt_text=build_alt_text(subject),
        sha256=sha256,
        storage_path=str(path),
        cost_usd=meta["cost_usd"],
    )
    session.add(asset)
    session.commit()
    return asset, True


def load_bytes(asset: MediaAsset) -> bytes:
    path = Path(asset.storage_path)
    if not path.is_file():
        raise MediaGenerationError("media bytes missing from storage volume")
    return path.read_bytes()


def get_or_create_rendered(
    session: Session, tenant_id: str, image_png: bytes, alt_source_text: str
) -> MediaAsset:
    """Wrap a renderer output in an asset row so WordPress photos get the same
    wp_media_id receipt resumability as generated visuals (rule 8)."""
    sha256 = hashlib.sha256(image_png).hexdigest()
    existing = session.scalar(
        select(MediaAsset).where(
            MediaAsset.tenant_id == tenant_id,  # rule 6
            MediaAsset.sha256 == sha256,
        )
    )
    if existing is not None:
        return existing
    tenant_dir = _storage_dir() / tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    path = tenant_dir / f"{sha256}.png"
    path.write_bytes(image_png)
    first_line = next(
        (line.strip() for line in alt_source_text.splitlines() if line.strip()), ""
    )
    asset = MediaAsset(
        tenant_id=tenant_id,
        kind="rendered",
        provider="renderer",
        alt_text=build_alt_text(first_line or "محتوای برند"),
        sha256=sha256,
        storage_path=str(path),
        status="approved",  # rendered from an APPROVED draft's frozen text
    )
    session.add(asset)
    session.flush()
    return asset
