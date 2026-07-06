import hashlib
import io
import math
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import Float, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rpim_core_api.brain import crawler
from rpim_core_api.brain.chunking import chunk_text
from rpim_core_api.brain.embed_client import embed_texts
from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.models import BrainChunk, BrainSource
from rpim_core_api.schemas import CrawlIn, CrawlOut, SourceIn, SourceOut

router = APIRouter(prefix="/brain", tags=["brain"])


def _existing_source(session: Session, tenant_id: str, content_hash: str) -> SourceOut | None:
    existing = session.scalar(
        select(BrainSource).where(
            BrainSource.tenant_id == tenant_id,
            BrainSource.content_hash == content_hash,
        )
    )
    if existing is None:
        return None
    chunk_ids = session.scalars(
        select(BrainChunk.id).where(
            BrainChunk.tenant_id == tenant_id,
            BrainChunk.source_id == existing.id,
        )
    ).all()
    return SourceOut(source_id=existing.id, chunks=len(chunk_ids))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _ingest(session: Session, identity: Identity, title: str, kind: str, text: str) -> SourceOut:
    pieces = chunk_text(text)
    if not pieces:
        raise HTTPException(status_code=422, detail="empty text")

    # Idempotent across retries (tunnel drops mid-request): identical content
    # for the same tenant returns the existing source — no re-embed, no dupes.
    content_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    existing_out = _existing_source(session, identity.tenant_id, content_hash)
    if existing_out is not None:
        return existing_out

    vectors = embed_texts(pieces, tenant_id=identity.tenant_id)
    source = BrainSource(
        tenant_id=identity.tenant_id,
        title=title,
        kind=kind,
        content_hash=content_hash,
    )
    session.add(source)
    try:
        session.flush()
        for seq, (piece, vector) in enumerate(zip(pieces, vectors, strict=True)):
            session.add(
                BrainChunk(
                    tenant_id=identity.tenant_id,
                    source_id=source.id,
                    seq=seq,
                    text=piece,
                    embedding=vector,
                )
            )
        session.commit()
    except IntegrityError:
        # Concurrent retry won the (tenant_id, content_hash) race — resume by
        # returning the winner's source (rule 8: idempotent under tunnel drops).
        session.rollback()
        existing_out = _existing_source(session, identity.tenant_id, content_hash)
        if existing_out is not None:
            return existing_out
        raise
    return SourceOut(source_id=source.id, chunks=len(pieces))


@router.post("/sources", response_model=SourceOut, status_code=201)
def create_source(
    body: SourceIn,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> SourceOut:
    return _ingest(session, identity, title=body.title, kind=body.kind, text=body.text)


@router.post("/sources/crawl", response_model=CrawlOut, status_code=201)
def create_source_crawl(
    body: CrawlIn,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> CrawlOut:
    try:
        crawler.validate_public_http_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    text, pages = crawler.crawl_site(body.url, body.max_pages)
    if not text.strip():
        raise HTTPException(status_code=422, detail="no extractable text found on the site")
    out = _ingest(
        session,
        identity,
        title=urlparse(body.url).netloc or body.url,
        kind="crawl",
        text=text,
    )
    return CrawlOut(source_id=out.source_id, chunks=out.chunks, pages=pages)


@router.post("/sources/pdf", response_model=SourceOut, status_code=201)
def create_source_pdf(
    file: UploadFile = File(...),
    title: str = Form(min_length=1, max_length=500),
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> SourceOut:
    raw = file.file.read()
    try:
        reader = PdfReader(io.BytesIO(raw))
        text = "\n\n".join(
            stripped
            for page in reader.pages
            if (stripped := (page.extract_text() or "").strip())
        )
    except PdfReadError as exc:
        raise HTTPException(status_code=422, detail="invalid PDF") from exc
    if not text.strip():
        raise HTTPException(status_code=422, detail="no extractable text in PDF")
    return _ingest(session, identity, title=title, kind="pdf", text=text)


@router.get("/search")
def search(
    q: str = Query(min_length=1),
    k: int = Query(default=5, ge=1, le=20),
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    query_vector = embed_texts([q], tenant_id=identity.tenant_id)[0]
    # tenant_id scoping is absolute (rule 6) — filtered on both join sides.
    base = (
        select(BrainChunk, BrainSource.title)
        .join(BrainSource, BrainChunk.source_id == BrainSource.id)
        .where(
            BrainChunk.tenant_id == identity.tenant_id,
            BrainSource.tenant_id == identity.tenant_id,
        )
    )

    if session.get_bind().dialect.name == "postgresql":
        # pgvector ANN path (<2s acceptance target; HNSW index, ADR 0011).
        # Explicit Float return type — otherwise SQLAlchemy inherits the
        # vector column type and runs the vector result-processor on the
        # scalar distance (TypeError: 'float' is not subscriptable).
        distance = BrainChunk.embedding.op("<=>", return_type=Float)(query_vector)
        rows = session.execute(base.add_columns(distance.label("d")).order_by("d").limit(k)).all()
        results = [
            {
                "text": chunk.text,
                "source_id": chunk.source_id,
                "source_title": title,
                "score": 1.0 - float(dist),
            }
            for chunk, title, dist in rows
        ]
        return {"results": results}

    # sqlite fallback (tests): python-side cosine over the tenant's chunks.
    rows = session.execute(base).all()
    scored = sorted(
        (
            {
                "text": chunk.text,
                "source_id": chunk.source_id,
                "source_title": title,
                "score": _cosine(query_vector, chunk.embedding),
            }
            for chunk, title in rows
        ),
        key=lambda r: r["score"],
        reverse=True,
    )
    return {"results": scored[:k]}
