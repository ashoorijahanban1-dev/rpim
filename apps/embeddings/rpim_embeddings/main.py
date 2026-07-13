import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from rpim_shared import HealthStatus, fake_embed

_model = None  # lazy singleton — bge-m3 load is expensive
# One loader at a time: concurrent first requests wait for the same load
# instead of constructing bge-m3 twice (each load is GBs of RAM).
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # image built without --extra model
        raise HTTPException(
            status_code=503, detail="model backend not installed (extra 'model')"
        ) from exc
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
    with _model_lock:
        if _model is None:
            _model = SentenceTransformer(
                model_name, device=os.environ.get("EMBEDDING_DEVICE", "cpu")
            )
    return _model


def _warm_model_in_background() -> None:
    """bge-m3 takes tens of seconds to load on CPU. Loading lazily on the
    first request made every post-redeploy first call time out cross-leg
    (it cost the pilot its first draft). Pay the load cost at boot, in a
    daemon thread so /health answers immediately."""
    if os.environ.get("EMBEDDING_BACKEND", "fake") != "real":
        return

    def _load() -> None:
        try:
            _get_model()
        except Exception:  # noqa: BLE001 — warmup is best-effort; requests surface real errors
            pass

    threading.Thread(target=_load, daemon=True).start()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _warm_model_in_background()
    yield


app = FastAPI(title="RPIM Embeddings", docs_url=None, redoc_url=None, lifespan=_lifespan)


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(service="embeddings", leg="us")


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1)


def _real_vectors(texts: list[str]) -> tuple[list[list[float]], str]:
    model = _get_model()
    encoded = model.encode(list(texts), normalize_embeddings=True)
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
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
