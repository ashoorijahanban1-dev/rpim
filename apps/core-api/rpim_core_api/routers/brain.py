import hashlib
import io
import math
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rpim_core_api.brain import crawler, service
from rpim_core_api.brain.chunking import chunk_text
from rpim_core_api.brain.embed_client import embed_texts
from rpim_core_api.brain.retrieval import search_chunks
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


MAX_CHUNKS = 300


def _ingest(
    session: Session,
    identity: Identity,
    title: str,
    kind: str,
    text: str,
    knowledge_kind: str = "doc",
    meta: dict | None = None,
) -> SourceOut:
    pieces = chunk_text(text)
    if not pieces:
        raise HTTPException(status_code=422, detail="empty text")
    if len(pieces) > MAX_CHUNKS:
        # A single giant source (book-sized PDF) would hold the request open
        # for minutes; ask for a split instead of timing out opaquely.
        raise HTTPException(status_code=422, detail="source too large — split the document")

    # Idempotent across retries (tunnel drops mid-request): identical content
    # for the same tenant returns the existing source — no re-embed, no dupes.
    content_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    existing_out = _existing_source(session, identity.tenant_id, content_hash)
    if existing_out is not None:
        return existing_out

    try:
        vectors = embed_texts(pieces, tenant_id=identity.tenant_id)
    except httpx.HTTPError as exc:
        # Cross-leg embedding down/slow is an operational condition, not a
        # server bug: surface a clean, dashboard-mappable 503 instead of a
        # bare 500 (production incident: large PDFs looked like a mystery).
        raise HTTPException(
            status_code=503, detail="embedding service unavailable — try again shortly"
        ) from exc
    source = BrainSource(
        tenant_id=identity.tenant_id,
        title=title,
        kind=kind,
        content_hash=content_hash,
        meta=meta,
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
                    kind=knowledge_kind,
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
    return _ingest(
        session,
        identity,
        title=body.title,
        kind=body.kind,
        text=body.text,
        knowledge_kind=body.knowledge_kind,
    )


def _canonical_product_text(product: "CatalogProduct") -> str:
    """Deterministic Persian block per catalog product — same input, same
    text, so the content-hash dedupe makes catalog replays upserts (rule 8)."""
    lines = [f"محصول: {product.name.strip()}"]
    if product.sku and product.sku.strip():
        lines.append(f"کد محصول: {product.sku.strip()}")
    if product.price and product.price.strip():
        lines.append(f"قیمت: {product.price.strip()}")
    features = [f.strip() for f in product.features if f.strip()]
    if features:
        lines.append("ویژگی‌ها: " + "، ".join(features))
    if product.url and product.url.strip():
        lines.append(f"لینک: {product.url.strip()}")
    return "\n".join(lines)


class CatalogProduct(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=100)
    price: str | None = Field(default=None, max_length=100)
    features: list[str] = Field(default_factory=list, max_length=20)
    url: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("product name must not be blank")
        return value


class CatalogIn(BaseModel):
    products: list[CatalogProduct] = Field(min_length=1, max_length=100)


@router.post("/catalog", status_code=201)
def ingest_catalog(
    body: CatalogIn,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    """Structured product-catalog door (M20): each product embeds as
    kind=product chunks with its raw structure kept in brain_sources.meta."""
    before = set(
        session.scalars(
            select(BrainSource.content_hash).where(
                BrainSource.tenant_id == identity.tenant_id  # rule 6
            )
        ).all()
    )
    ingested = skipped = 0
    for product in body.products:
        text = _canonical_product_text(product)
        content_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        if content_hash in before:
            skipped += 1
            continue
        _ingest(
            session,
            identity,
            title=product.name.strip(),
            kind="catalog",
            text=text,
            knowledge_kind="product",
            meta=product.model_dump(),
        )
        before.add(content_hash)
        ingested += 1
    return {"ingested": ingested, "skipped": skipped}


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
        # PasswordType.NOT_DECRYPTED is falsy; an empty user password is the
        # only automatic attempt we make.
        if reader.is_encrypted and not reader.decrypt(""):
            raise HTTPException(
                status_code=422,
                detail="password-protected PDF — remove the password and retry",
            )
        text = "\n\n".join(
            stripped
            for page in reader.pages
            if (stripped := (page.extract_text() or "").strip())
        )
    except HTTPException:
        raise
    except PdfReadError as exc:
        raise HTTPException(status_code=422, detail="invalid PDF") from exc
    except Exception as exc:
        # pypdf raises beyond PdfReadError on exotic/corrupt/AES-only files
        # (e.g. DependencyError) — malformed INPUT is a 422, never a 500.
        raise HTTPException(status_code=422, detail="invalid or unreadable PDF") from exc
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="no extractable text in PDF (scanned image-only file?)",
        )
    return _ingest(session, identity, title=title, kind="pdf", text=text)


@router.post("/reindex")
def reindex(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    """Re-embed every chunk of the calling tenant with the CURRENT backend.

    Recovery path for sources ingested while the embedding backend was fake
    (or after a model upgrade): the content-hash dedup rightly refuses to
    re-ingest identical text, so vectors must be refreshed in place.
    Idempotent — safe to re-run (rule 8)."""
    chunks = session.scalars(
        select(BrainChunk)
        .where(BrainChunk.tenant_id == identity.tenant_id)  # rule 6
        .order_by(BrainChunk.source_id, BrainChunk.seq)
    ).all()
    if chunks:
        try:
            vectors = embed_texts([c.text for c in chunks], tenant_id=identity.tenant_id)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail="embedding service unavailable — try again shortly"
            ) from exc
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector
        session.commit()
    return {
        "chunks": len(chunks),
        "sources": len({c.source_id for c in chunks}),
    }


@router.get("/search")
def search(
    q: str = Query(min_length=1),
    k: int = Query(default=5, ge=1, le=20),
    kinds: str | None = Query(default=None),
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    # Explicit search stays STRICT (no doc-widening) — the graceful fallback
    # belongs to prompt-building consumers via BrandBrain (M20 design §3.1).
    kind_list: list[str] | None = None
    if kinds:
        kind_list = [part.strip() for part in kinds.split(",") if part.strip()]
        unknown = [part for part in kind_list if part not in service.KINDS]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown kinds: {unknown}")
    query_vector = embed_texts([q], tenant_id=identity.tenant_id)[0]
    return {
        "results": search_chunks(
            session, identity.tenant_id, query_vector, k, kinds=kind_list
        )
    }
