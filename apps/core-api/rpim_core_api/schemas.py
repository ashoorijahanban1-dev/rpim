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


class SourceOut(BaseModel):
    source_id: str
    chunks: int
