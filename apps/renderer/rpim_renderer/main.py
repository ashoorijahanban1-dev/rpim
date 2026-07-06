import base64
import hashlib
import os
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from rpim_renderer.rendering import fake_png
from rpim_renderer.templates import SIZES, html_for
from rpim_shared import HealthStatus

app = FastAPI(title="RPIM Renderer", docs_url=None, redoc_url=None)


def _require_internal(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(service="renderer", leg="us")


class TextIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=2000)
    cta: str = Field(default="", max_length=200)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class RenderIn(BaseModel):
    template: Literal["announce", "quote", "product"]
    size: Literal["square", "story", "wide"]
    tenant_id: str = Field(min_length=1, max_length=64)
    text: TextIn


@app.post("/render")
def render(body: RenderIn, x_internal_token: str | None = Header(default=None)) -> dict:
    _require_internal(x_internal_token)

    mode = os.environ.get("RENDER_MODE", "fake")
    width, height = SIZES[body.size]
    text_sha256 = hashlib.sha256(
        f"{body.text.title}\n{body.text.body}\n{body.text.cta}".encode()
    ).hexdigest()
    # The HTML is built in every mode: Persian text always comes from the
    # template engine, and the fake image is seeded by template+size+text so
    # identical requests stay byte-identical (idempotent cross-leg jobs).
    html = html_for(body.template, body.size, body.text.model_dump())

    if mode != "fake":
        # Chromium screenshot path is slice B; refuse loudly, never a false PNG.
        raise HTTPException(
            status_code=503,
            detail="live rendering lands in M8 slice B — set RENDER_MODE=fake",
        )
    html_sha = hashlib.sha256(html.encode()).hexdigest()
    image = fake_png(width, height, seed=f"{body.template}:{body.size}:{html_sha}")

    return {
        "image_b64": base64.b64encode(image).decode("ascii"),
        "meta": {
            "template": body.template,
            "size": body.size,
            "width": width,
            "height": height,
            "render_mode": mode,
            "tenant_id": body.tenant_id,
            "text_sha256": text_sha256,
        },
    }
