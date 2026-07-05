import os

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from rpim_model_gateway.ledger import record
from rpim_shared import HealthStatus, fake_embed

app = FastAPI(title="RPIM Model Gateway", docs_url=None, redoc_url=None)


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(service="model-gateway", leg="us")


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1)
    tenant_id: str | None = None


@app.post("/embed")
def embed(body: EmbedIn, x_internal_token: str | None = Header(default=None)) -> dict:
    # Cross-leg auth: only the iran leg (sharing INTERNAL_TOKEN) may call.
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")

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
