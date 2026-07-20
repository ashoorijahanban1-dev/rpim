import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity, require_editor
from rpim_core_api.measurement import attribution
from rpim_core_api.measurement.utm import build_landing_url
from rpim_core_api.models import ContentDraft, MediaAsset, PublishJob
from rpim_core_api.publisher.engine import dispatch_due_jobs

router = APIRouter(prefix="/publish", tags=["publish"])

# Only drafts that went through the human approval gate compile (rule 1).
PUBLISHABLE_STATUSES = ("approved", "edited")


class ImageSpecIn(BaseModel):
    # M21: template = renderer HTML templates (M12); generated = an APPROVED
    # media asset from the studio (rule 1 covers images too).
    kind: Literal["template", "generated"] = "template"
    template: Literal["announce", "quote", "product"] | None = None
    size: Literal["square", "story", "wide"] | None = None
    media_asset_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> "ImageSpecIn":
        if self.kind == "template" and (self.template is None or self.size is None):
            raise ValueError("template image needs template and size")
        if self.kind == "generated" and not self.media_asset_id:
            raise ValueError("generated image needs media_asset_id")
        return self


class PublishJobIn(BaseModel):
    draft_id: str
    channel: Literal["telegram", "bale", "eitaa", "wordpress"]
    chat_id: str = Field(min_length=1, max_length=128)
    campaign_code: str = Field(min_length=1, max_length=120)
    scheduled_at: datetime | None = None
    landing_url: str | None = Field(default=None, max_length=900)
    image: ImageSpecIn | None = None

    @field_validator("campaign_code")
    @classmethod
    def _campaign_code_not_blank(cls, value: str) -> str:
        # Rule 3: no publish job without a real campaign code.
        stripped = value.strip()
        if not stripped:
            raise ValueError("campaign_code must not be blank")
        return stripped

    @field_validator("landing_url")
    @classmethod
    def _landing_url_scheme(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Same rule the compiler enforces — reject early with a 422.
        build_landing_url(value, {})
        return value


def _build_utm(channel: str, campaign_code: str, tenant_id: str) -> dict:
    return {
        "utm_source": channel,
        "utm_medium": "social",
        "utm_campaign": campaign_code,
        # M22 (ADR 0041): tenant attribution key — campaign codes are free
        # strings on a SHARED analytics site; without this, two brands using
        # the same code would ingest each other's clicks (rule 6).
        "utm_id": attribution.tenant_key(tenant_id),
    }


def _job_out(job: PublishJob) -> dict:
    return {
        "job_id": job.id,
        "draft_id": job.draft_id,
        "channel": job.channel,
        "chat_id": job.chat_id,
        "campaign_code": job.campaign_code,
        "utm": job.utm,
        "landing_url": job.landing_url,
        "image_spec": job.image_spec,
        "status": job.status,
        "attempts": job.attempts,
        "scheduled_at": job.scheduled_at,
        "sent_at": job.sent_at,
        "created_at": job.created_at,
    }


@router.post("/jobs", status_code=201)
def create_job(
    body: PublishJobIn,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    draft = session.scalar(
        select(ContentDraft).where(
            ContentDraft.tenant_id == identity.tenant_id,  # rule 6
            ContentDraft.id == body.draft_id,
        )
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    if draft.status not in PUBLISHABLE_STATUSES:
        raise HTTPException(status_code=409, detail="draft is not approved for publishing")

    if body.image is not None and body.image.kind == "generated":
        # Rule 1 covers IMAGES: only a human-approved asset may attach; the
        # lookup is tenant-scoped so a foreign id is simply invisible (rule 6).
        asset = session.scalar(
            select(MediaAsset).where(
                MediaAsset.tenant_id == identity.tenant_id,  # rule 6
                MediaAsset.id == body.image.media_asset_id,
            )
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="media asset not found")
        if asset.status not in ("approved", "attached"):
            raise HTTPException(
                status_code=409, detail="media asset is not approved for publishing"
            )
        asset.status = "attached"

    utm = _build_utm(body.channel, body.campaign_code, identity.tenant_id)
    job = PublishJob(
        tenant_id=identity.tenant_id,
        draft_id=draft.id,
        channel=body.channel,
        chat_id=body.chat_id,
        campaign_code=body.campaign_code,
        utm=utm,
        # UTM params compiled into the landing link at job birth (M9).
        landing_url=build_landing_url(body.landing_url, utm) if body.landing_url else None,
        # Stored shape stays IDENTICAL to pre-M21 rows for template posts
        # ({template, size}); only generated posts carry the new fields.
        image_spec=(
            {
                key: value
                for key, value in body.image.model_dump(exclude_none=True).items()
                if not (key == "kind" and value == "template")
            }
            if body.image
            else None
        ),
        # Frozen at compile time: what was approved is exactly what ships.
        text=draft.edited_text or draft.text,
        scheduled_at=body.scheduled_at,
    )
    session.add(job)
    session.commit()
    return {
        "job_id": job.id,
        "status": job.status,
        "utm": job.utm,
        "landing_url": job.landing_url,
        "image_spec": job.image_spec,
    }


@router.get("/jobs")
def list_jobs(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    jobs = session.scalars(
        select(PublishJob)
        .where(PublishJob.tenant_id == identity.tenant_id)  # rule 6
        .order_by(PublishJob.created_at.desc())
    ).all()
    return {"jobs": [_job_out(job) for job in jobs]}


@router.post("/dispatch")
def dispatch(
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    # Internal ops surface (called by the beat scheduler in slice B), not
    # tenant auth — same trust boundary as /governance/kill.
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")
    return dispatch_due_jobs(session)


@router.post("/jobs/{job_id}/requeue")
def requeue_job(
    job_id: str,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    """M21 dead-letter exit: revive a STALLED job after the operator fixed
    the underlying cause. Only stalled jobs qualify — queued/sent jobs 409."""
    job = session.scalar(
        select(PublishJob).where(
            PublishJob.tenant_id == identity.tenant_id,  # rule 6
            PublishJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "stalled":
        raise HTTPException(status_code=409, detail="only stalled jobs can be requeued")
    job.status = "queued"
    job.first_failed_at = None
    job.last_error = None
    session.commit()
    return {"job_id": job.id, "status": job.status}
