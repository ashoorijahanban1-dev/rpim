import os
from typing import Literal

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from rpim_model_gateway import idempotency, telegram
from rpim_model_gateway.ledger import entries_for, record
from rpim_model_gateway.providers import PROVIDERS, cost_usd
from rpim_shared import HealthStatus, fake_embed

app = FastAPI(title="RPIM Model Gateway", docs_url=None, redoc_url=None)


def _require_internal(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(service="model-gateway", leg="us")


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1)
    tenant_id: str | None = None


@app.post("/embed")
def embed(body: EmbedIn, x_internal_token: str | None = Header(default=None)) -> dict:
    # Cross-leg auth: only the iran leg (sharing INTERNAL_TOKEN) may call.
    _require_internal(x_internal_token)

    backend = os.environ.get("EMBEDDING_BACKEND", "fake")
    if backend == "fake":
        vectors = [fake_embed(text) for text in body.texts]
        model = "fake"
        payload = {"vectors": vectors, "model": model, "dim": len(vectors[0]) if vectors else 1024}
    else:
        # T3 real backend: forward to the embeddings service (same leg).
        url = os.environ.get("EMBEDDINGS_URL", "http://embeddings:8090")
        try:
            response = httpx.post(
                f"{url.rstrip('/')}/embed",
                json={"texts": body.texts},
                headers={"X-Internal-Token": x_internal_token},
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="embeddings backend unreachable") from exc
        model = payload.get("model", backend)

    record(tenant_id=body.tenant_id, task="embed", model=model, units=len(body.texts))
    return payload


class CompleteIn(BaseModel):
    task: Literal["t1", "t2"]
    prompt: str = Field(min_length=1)
    system: str | None = None
    tenant_id: str | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    # Cross-leg idempotency (rule 8): retries after a tunnel drop reuse the
    # cached response instead of re-calling the provider / double-charging.
    request_id: str | None = Field(default=None, max_length=64)


def _chain_for(task: str) -> list[str]:
    if task == "t2":
        primary = os.environ.get("MODEL_T2", "")
        if not primary:
            # Constitution: MODEL_T2 stays unset until the 50-prompt Persian
            # eval decides it — the gateway says so instead of guessing.
            raise HTTPException(
                status_code=503,
                detail="MODEL_T2 is unset — awaiting the 50-prompt Persian eval (phase 0)",
            )
        fallbacks = os.environ.get("MODEL_T2_FALLBACKS", "")
    else:
        primary = os.environ.get("MODEL_T1", "")
        fallbacks = os.environ.get("MODEL_T1_FALLBACKS", "")
    links = [x.strip() for x in [primary, *fallbacks.split(",")] if x.strip()]
    if not links:
        raise HTTPException(status_code=503, detail=f"no model configured for task {task}")
    return links


@app.post("/complete")
def complete_text(body: CompleteIn, x_internal_token: str | None = Header(default=None)) -> dict:
    _require_internal(x_internal_token)

    # Idempotency key is tenant-scoped (rule 6): another tenant reusing the
    # same request_id must never receive this tenant's cached payload.
    idem_key = f"{body.tenant_id or 'unknown'}:{body.request_id}" if body.request_id else None
    if idem_key:
        cached = idempotency.get(idem_key)
        if cached is not None:
            return cached

    timeout = float(os.environ.get("MODEL_TIMEOUT_S", "60"))
    errors: list[str] = []
    for link in _chain_for(body.task):
        provider_name, _, model = link.partition(":")
        provider = PROVIDERS.get(provider_name)
        if provider is None:
            errors.append(f"{link}: unknown provider")
            continue
        try:
            result = provider(
                model,
                body.prompt,
                system=body.system,
                max_tokens=body.max_tokens,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — any link failure falls through the chain
            errors.append(f"{link}: {type(exc).__name__}: {exc}")
            continue

        cost = cost_usd(model, result["tokens_in"], result["tokens_out"])
        payload = {
            "text": result["text"],
            "provider": provider_name,
            "model": model,
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
            "cost_usd": cost,
        }
        # Cache BEFORE the ledger write: if we crash between the two, a retry
        # under-charges once instead of double-charging (deliberate asymmetry
        # — the cheap failure mode for the tenant, rule 8).
        if idem_key:
            idempotency.put(idem_key, payload)
        record(
            tenant_id=body.tenant_id,
            task=f"complete:{body.task}",
            model=model,
            units=result["tokens_in"] + result["tokens_out"],
            provider=provider_name,
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            cost_usd=cost,
        )
        return payload

    raise HTTPException(status_code=503, detail=f"all model links failed: {'; '.join(errors)}")


class TelegramIn(BaseModel):
    chat_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    # Cross-leg idempotency key (rule 8) — the iran leg sends its job_id.
    request_id: str | None = Field(default=None, max_length=128)


@app.post("/publish/telegram")
def publish_telegram(
    body: TelegramIn, x_internal_token: str | None = Header(default=None)
) -> dict:
    # Cross-leg seam (rule 5): the iran leg forwards telegram jobs here; only
    # this us-leg process talks to api.telegram.org.
    _require_internal(x_internal_token)
    idem_key = f"tgpub:{body.request_id}" if body.request_id else None
    if idem_key:
        cached = idempotency.get(idem_key)
        if cached is not None:
            return cached
    try:
        result = telegram.send_telegram(body.chat_id, body.text)
    except telegram.TelegramNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except telegram.TelegramSendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Cache only AFTER a successful send: a failed send must stay retryable,
    # a succeeded one must never double-post (rule 8).
    if idem_key:
        idempotency.put(idem_key, result)
    return result


@app.post("/publish/telegram-photo")
async def publish_telegram_photo(
    chat_id: str = Form(min_length=1),
    caption: str = Form(default=""),
    photo: UploadFile = File(),
    request_id: str | None = Form(default=None),
    x_internal_token: str | None = Header(default=None),
) -> dict:
    # Cross-leg multipart seam (rule 5): the iran leg forwards photo posts
    # here; only this us-leg process talks to api.telegram.org.
    _require_internal(x_internal_token)
    idem_key = f"tgpub:{request_id}" if request_id else None
    if idem_key:
        cached = idempotency.get(idem_key)
        if cached is not None:
            return cached
    image_png = await photo.read()
    try:
        result = telegram.send_telegram_photo(chat_id, caption, image_png)
    except telegram.TelegramNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except telegram.TelegramSendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if idem_key:
        idempotency.put(idem_key, result)
    return result


@app.get("/ledger/{tenant_id}")
def ledger(tenant_id: str, x_internal_token: str | None = Header(default=None)) -> dict:
    _require_internal(x_internal_token)
    entries = entries_for(tenant_id)
    return {
        "entries": entries,
        "total_cost_usd": round(sum(e.get("cost_usd", 0.0) for e in entries), 8),
    }
