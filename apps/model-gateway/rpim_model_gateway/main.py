import os

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
    else:
        # T3 real backend (bge-m3 service) lands in M2 slice B; until then the
        # gateway is honest about unavailability instead of pretending.
        raise HTTPException(status_code=503, detail=f"embedding backend '{backend}' not wired yet")

    record(tenant_id=body.tenant_id, task="embed", model=model, units=len(body.texts))
    return {"vectors": vectors, "model": model, "dim": len(vectors[0]) if vectors else 1024}
