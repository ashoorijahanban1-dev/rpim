import json
from importlib import resources

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity, require_owner
from rpim_core_api.models import BrandProfile, OnboardingInterview
from rpim_core_api.schemas import AnswersIn, CompleteOut, InterviewOut

router = APIRouter(prefix="/onboarding/interview", tags=["onboarding"])

_QUESTIONS: list[dict] = json.loads(
    resources.files("rpim_core_api").joinpath("data/onboarding_fa.json").read_text("utf-8")
)["questions"]
_FIELDS = [q["field"] for q in _QUESTIONS]
_LIST_FIELDS = {q["field"] for q in _QUESTIONS if q["kind"] == "list"}


def _get_scoped(session: Session, tenant_id: str) -> OnboardingInterview | None:
    # tenant_id scoping is absolute (CLAUDE.md rule 6).
    return session.scalar(
        select(OnboardingInterview).where(OnboardingInterview.tenant_id == tenant_id)
    )


@router.get("", response_model=InterviewOut)
def get_interview(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> InterviewOut:
    interview = _get_scoped(session, identity.tenant_id)
    return InterviewOut(
        status=interview.status if interview else "draft",
        questions=_QUESTIONS,
        answers=interview.answers if interview else {},
    )


@router.put("/answers", response_model=InterviewOut)
def put_answers(
    body: AnswersIn,
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> InterviewOut:
    unknown = set(body.answers) - set(_FIELDS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown fields: {', '.join(sorted(unknown))}")

    interview = _get_scoped(session, identity.tenant_id)
    if interview is None:
        interview = OnboardingInterview(tenant_id=identity.tenant_id, answers={})
        session.add(interview)
    merged = dict(interview.answers or {})
    merged.update(body.answers)
    interview.answers = merged
    interview.status = "draft"  # any edit re-opens the interview
    session.commit()
    return InterviewOut(status=interview.status, questions=_QUESTIONS, answers=interview.answers)


@router.post("/complete", response_model=CompleteOut)
def complete(
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> CompleteOut:
    interview = _get_scoped(session, identity.tenant_id)
    answers = dict(interview.answers or {}) if interview else {}
    missing = [f for f in _FIELDS if f not in answers or answers[f] in ("", [], {}, None)]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing answers: {', '.join(missing)}")

    tone = answers["tone"]
    lexicon = answers["lexicon"]
    if not isinstance(tone, str) or not isinstance(lexicon, dict):
        raise HTTPException(status_code=422, detail="tone must be text and lexicon a mapping")
    for field in _LIST_FIELDS:
        if not isinstance(answers[field], list):
            raise HTTPException(status_code=422, detail=f"{field} must be a list")

    # The confirmed interview IS the brand profile (blueprint M1 scope).
    profile = session.scalar(
        select(BrandProfile).where(BrandProfile.tenant_id == identity.tenant_id)
    )
    if profile is None:
        profile = BrandProfile(tenant_id=identity.tenant_id)
        session.add(profile)
    profile.tone = tone
    profile.personas = answers["personas"]
    profile.lexicon = lexicon
    profile.allowed_claims = answers["allowed_claims"]
    profile.forbidden_claims = answers["forbidden_claims"]
    profile.red_lines = answers["red_lines"]

    assert interview is not None  # guaranteed: missing-check above requires answers
    interview.status = "completed"
    session.commit()
    return CompleteOut(status="completed")
