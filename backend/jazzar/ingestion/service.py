"""Pipeline d'ingestion : document brut -> nettoyage -> chunks -> embeddings -> Postgres.

Un `RawDocument` est la représentation pivot, quelle que soit la source (PDF, Markdown, Wikipedia).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jazzar.config import get_settings
from jazzar.ingestion.embeddings import get_embedder
from jazzar.logging import get_logger
from jazzar.models import Chunk, Document, PollResult, Review, Source
from jazzar.text import chunk as split_chunks
from jazzar.text import estimate_tokens, hamming, simhash, to_signed64

log = get_logger(__name__)


@dataclass
class RawPage:
    number: int | None
    text: str


@dataclass
class RawReview:
    album_title: str
    artist: str
    label: str | None = None
    release_year: int | None = None
    genre: str | None = None
    rating: float | None = None
    reviewer: str | None = None
    excerpt: str | None = None


@dataclass
class RawPollResult:
    poll_name: str
    year: int
    category: str
    winner: str
    rank: int = 1
    points: int | None = None


@dataclass
class RawDocument:
    title: str
    doc_type: str  # article | review | poll | interview | wiki | liner_notes | blindfold
    pages: list[RawPage]
    author: str | None = None
    published_on: date | None = None
    issue: str | None = None
    language: str = "en"
    file_path: str | None = None
    url: str | None = None
    meta: dict = field(default_factory=dict)
    reviews: list[RawReview] = field(default_factory=list)
    polls: list[RawPollResult] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.full_text.encode("utf-8")).hexdigest()


def jsonable(value):
    """Rend une structure (en-tête YAML, métadonnées PDF) sérialisable en JSONB."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


@dataclass
class IngestStats:
    documents: int = 0
    chunks: int = 0
    skipped_duplicates: int = 0
    near_duplicate_chunks: int = 0


async def get_or_create_source(session: AsyncSession, kind: str, name: str, **kw) -> Source:
    res = await session.execute(select(Source).where(Source.kind == kind, Source.name == name))
    src = res.scalar_one_or_none()
    if src is None:
        src = Source(kind=kind, name=name, **kw)
        session.add(src)
        await session.flush()
    return src


# Un chunk plus court qu'un crédit photo ou un intertitre (« SHERVIN LAINEZ », « CRITICS CAPSULES »)
# n'apporte rien à la recherche et remonte à tort sur les requêtes par mots-clés.
MIN_CHUNK_CHARS = 60


def _chunk_document(raw: RawDocument) -> list[tuple[int | None, str, int]]:
    """Retourne (page, texte, tokens). Le chunking se fait page par page pour garder la page de citation."""
    s = get_settings()
    out: list[tuple[int | None, str, int]] = []
    for page in raw.pages:
        if not page.text.strip():
            continue
        for _start, _end, text in split_chunks(page.text, s.chunk_target_tokens, s.chunk_overlap_tokens):
            if len(text.strip()) < MIN_CHUNK_CHARS:
                continue
            out.append((page.number, text, estimate_tokens(text)))
    return out


async def ingest_document(session: AsyncSession, source: Source, raw: RawDocument, stats: IngestStats) -> Document | None:
    content_hash = raw.content_hash
    exists = await session.execute(
        select(Document.id).where(Document.source_id == source.id, Document.content_hash == content_hash)
    )
    if exists.scalar_one_or_none():
        stats.skipped_duplicates += 1
        return None

    doc = Document(
        source_id=source.id,
        title=raw.title,
        author=raw.author,
        doc_type=raw.doc_type,
        published_on=raw.published_on,
        year=raw.published_on.year if raw.published_on else raw.meta.get("year"),
        issue=raw.issue,
        language=raw.language,
        file_path=raw.file_path,
        url=raw.url,
        page_start=min((p.number for p in raw.pages if p.number), default=None),
        page_end=max((p.number for p in raw.pages if p.number), default=None),
        content_hash=content_hash,
        meta=jsonable(raw.meta),
    )
    session.add(doc)
    await session.flush()

    pieces = _chunk_document(raw)
    # Déduplication quasi-exacte intra-document (colonnes OCR répétées, en-têtes) via simhash.
    kept: list[tuple[int | None, str, int, int]] = []
    seen: list[int] = []
    for page, text, tokens in pieces:
        h = simhash(text)
        if any(hamming(h, s) <= 3 for s in seen):
            stats.near_duplicate_chunks += 1
            continue
        seen.append(h)
        kept.append((page, text, tokens, h))

    if kept:
        embedder = get_embedder()
        vectors = await embedder.aencode([k[1] for k in kept])
        for ordinal, ((page, text, tokens, h), vec) in enumerate(zip(kept, vectors, strict=True)):
            session.add(
                Chunk(
                    document_id=doc.id,
                    ordinal=ordinal,
                    page=page,
                    text=text,
                    token_count=tokens,
                    simhash=to_signed64(h),
                    embedding=vec.tolist(),
                )
            )
        stats.chunks += len(kept)

    for r in raw.reviews:
        session.add(
            Review(
                document_id=doc.id,
                album_title=r.album_title,
                artist=r.artist,
                label=r.label,
                release_year=r.release_year,
                review_year=doc.year,
                review_date=raw.published_on,
                reviewer=r.reviewer or raw.author,
                rating=r.rating,
                genre=(r.genre or "").lower() or None,
                excerpt=r.excerpt or (raw.full_text[:600] if raw.full_text else None),
            )
        )
    for p in raw.polls:
        session.add(
            PollResult(
                document_id=doc.id,
                poll_name=p.poll_name,
                year=p.year,
                category=p.category,
                winner=p.winner,
                rank=p.rank,
                points=p.points,
            )
        )
    stats.documents += 1
    log.info("ingest.document", title=raw.title, chunks=len(kept), reviews=len(raw.reviews), polls=len(raw.polls))
    return doc
