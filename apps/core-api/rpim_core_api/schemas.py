from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str = Field(min_length=1, max_length=200)


class RegisterOut(BaseModel):
    tenant_id: str
    access_token: str
    token_type: str = "bearer"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BrandProfileIn(BaseModel):
    tone: str = ""
    personas: list[str] = Field(default_factory=list)
    lexicon: dict[str, str] = Field(default_factory=dict)
    allowed_claims: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    red_lines: list[str] = Field(default_factory=list)


class BrandProfileOut(BrandProfileIn):
    pass


class AnswersIn(BaseModel):
    answers: dict


class InterviewOut(BaseModel):
    status: str
    questions: list[dict]
    answers: dict


class CompleteOut(BaseModel):
    status: str


class SourceIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    kind: str = "upload"
    text: str
    # M20 retrieval facet — separate from `kind` (provenance).
    knowledge_kind: Literal["product", "tone", "faq", "claim", "doc"] = "doc"


class SourceOut(BaseModel):
    source_id: str
    chunks: int


class CrawlIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    max_pages: int = Field(default=5, ge=1, le=10)


class CrawlOut(SourceOut):
    pages: int


class Brief(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    audience: str = Field(min_length=1, max_length=500)
    channel: str = Field(min_length=1, max_length=100)
    format: str = Field(min_length=1, max_length=100)
    hook: str | None = None
    cta: str | None = None


class BriefIn(BaseModel):
    brief: Brief


class DraftOut(BaseModel):
    draft_id: str
    text: str
    context_refs: list[str]
    flag_unsourced: bool
    status: str


class EditIn(BaseModel):
    edited_text: str = Field(min_length=1, max_length=8000)


class RejectIn(BaseModel):
    reason_code: Literal["tone", "fact", "sensitivity", "taste"]
    note: str | None = None
