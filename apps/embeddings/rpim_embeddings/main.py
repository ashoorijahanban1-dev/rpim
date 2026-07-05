import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from rpim_shared import HealthStatus, fake_embed

app = FastAPI(title="RPIM Embeddings", docs_url=None, redoc_url=None)

_model = None  # lazy singleton — bge-m3 load is expensive


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(service="embeddings", leg="us")


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1)


def _real_vectors(texts: list[str]) -> tuple[list[list[float]], str]:
    global _model
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # image built without --extra model
            raise HTTPException(
                status_code=503, detail="model backend not installed (extra 'model')"
            ) from exc
        _model = SentenceTransformer(
            model_name, device=os.environ.get("EMBEDDING_DEVICE", "cpu")
        )
    encoded = _model.encode(list(texts), normalize_embeddings=True)
    return [[float(x) for x in vector] for vector in encoded], model_name


@app.post("/embed")
def embed(body: EmbedIn, x_internal_token: str | None = Header(default=None)) -> dict:
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")

    backend = os.environ.get("EMBEDDING_BACKEND", "fake")
    if backend == "fake":
        vectors = [fake_embed(text) for text in body.texts]
        model = "fake"
    else:
        vectors, model = _real_vectors(body.texts)

    return {"vectors": vectors, "model": model, "dim": len(vectors[0]) if vectors else 1024}
