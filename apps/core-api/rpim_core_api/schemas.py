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
    forbidden_claims: list[str] = Field(default_factory=list)
    red_lines: list[str] = Field(default_factory=list)


class BrandProfileOut(BrandProfileIn):
    pass
