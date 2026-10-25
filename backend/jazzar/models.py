"""Modèle relationnel Jazzar.

Deux familles de tables :
- Corpus : sources -> documents -> chunks (texte + embedding + tsvector) pour le RAG.
- Métadonnées structurées : reviews (notes étoilées), polls, artists pour le BI / Text-to-SQL.
Plus les tables d'exploitation : llm_calls (coûts), queries (historique + feedback), dossiers, eval_runs.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, list: JSONB}  # noqa: RUF012


class Source(Base):
    """Provenance d'un lot de documents (DownBeat, Wikipedia, MusicBrainz, corpus local...)."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # downbeat | wikipedia | musicbrainz | local | sample
    name: Mapped[str] = mapped_column(String(200))
    license: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    documents: Mapped[list[Document]] = relationship(back_populates="source")


class Document(Base):
    """Une unité éditoriale : article, critique d'album, résultat de poll, page encyclopédique."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "content_hash", name="uq_documents_source_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200), index=True)
    doc_type: Mapped[str] = mapped_column(String(32), index=True)  # article | review | poll | interview | wiki | liner_notes | blindfold
    published_on: Mapped[date | None] = mapped_column(Date, index=True)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    issue: Mapped[str | None] = mapped_column(String(100))  # ex. "Vol. 32 No. 14, July 1, 1965"
    language: Mapped[str] = mapped_column(String(8), default="en")
    file_path: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped[Source] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")
    reviews: Mapped[list[Review]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """Fragment indexé d'un document : texte brut, embedding dense et vecteur plein-texte."""

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_document_ordinal", "document_id", "ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))

    document: Mapped[Document] = relationship(back_populates="chunks")


class Review(Base):
    """Critique d'album notée (cœur du BI : notes, genres, labels, années)."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    album_title: Mapped[str] = mapped_column(Text, index=True)
    artist: Mapped[str] = mapped_column(Text, index=True)
    label: Mapped[str | None] = mapped_column(String(120), index=True)
    release_year: Mapped[int | None] = mapped_column(Integer, index=True)
    review_year: Mapped[int | None] = mapped_column(Integer, index=True)
    review_date: Mapped[date | None] = mapped_column(Date)
    reviewer: Mapped[str | None] = mapped_column(String(200))
    rating: Mapped[float | None] = mapped_column(Numeric(2, 1))  # étoiles 0.0 – 5.0
    genre: Mapped[str | None] = mapped_column(String(80), index=True)  # bebop | hard bop | free jazz | fusion | ...
    excerpt: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

    document: Mapped[Document | None] = relationship(back_populates="reviews")


class PollResult(Base):
    """Résultat d'un sondage (Critics Poll, Readers Poll) : année, catégorie, lauréat."""

    __tablename__ = "polls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    poll_name: Mapped[str] = mapped_column(String(80), index=True)  # "Critics Poll" | "Readers Poll"
    year: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)  # "Trumpet", "Jazz Album of the Year"...
    winner: Mapped[str] = mapped_column(Text, index=True)
    rank: Mapped[int] = mapped_column(Integer, default=1)
    points: Mapped[int | None] = mapped_column(Integer)


class Artist(Base):
    """Fiche artiste minimale, enrichie par MusicBrainz quand disponible."""

    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True)
    mbid: Mapped[str | None] = mapped_column(String(36), unique=True)
    instrument: Mapped[str | None] = mapped_column(String(80))
    birth_year: Mapped[int | None] = mapped_column(Integer)
    death_year: Mapped[int | None] = mapped_column(Integer)
    origin: Mapped[str | None] = mapped_column(String(120))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class LLMCall(Base):
    """Trace de chaque appel Claude : tokens, cache, coût, latence (observabilité et FinOps)."""

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(64), index=True)  # route | answer | plan | research | write | sql | judge
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class Query(Base):
    """Question posée au système, réponse, citations, route choisie et feedback utilisateur."""

    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)
    question: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="fr")
    route: Mapped[str | None] = mapped_column(String(32), index=True)  # lookup | semantic | synthesis | refuse | fallback_keyword | cache
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    feedback: Mapped[int | None] = mapped_column(SmallInteger)  # +1 / -1
    feedback_comment: Mapped[str | None] = mapped_column(Text)


class Dossier(Base):
    """Dossier de recherche généré par l'équipe d'agents."""

    __tablename__ = "dossiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    trace_id: Mapped[str] = mapped_column(String(36), index=True)
    brief: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="fr")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)  # queued | planning | researching | writing | reviewing | done | failed
    title: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[dict] = mapped_column(JSONB, default=dict)
    markdown: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    steps: Mapped[list] = mapped_column(JSONB, default=list)  # journal d'exécution des agents
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)


class EvalRun(Base):
    """Exécution du golden set : agrégats et détail par cas."""

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    system_version: Mapped[str] = mapped_column(String(200))
    golden_set: Mapped[str] = mapped_column(String(100))
    aggregate: Mapped[dict] = mapped_column(JSONB, default=dict)
    per_case: Mapped[list] = mapped_column(JSONB, default=list)
    passed_gates: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


# Description du schéma BI exposée au moteur Text-to-SQL (uniquement les tables analytiques).
BI_SCHEMA_DESCRIPTION = """
Tables disponibles (PostgreSQL, lecture seule) :

reviews(id, document_id, album_title TEXT, artist TEXT, label TEXT, release_year INT, review_year INT,
        review_date DATE, reviewer TEXT, rating NUMERIC(2,1) -- étoiles 0.0 à 5.0, genre TEXT, excerpt TEXT)
  Genres normalisés en minuscules : 'swing', 'bebop', 'hard bop', 'cool jazz', 'modal jazz', 'free jazz',
  'post-bop', 'fusion', 'latin jazz', 'vocal jazz', 'big band', 'avant-garde', 'soul jazz', 'contemporary'.

polls(id, poll_name TEXT -- 'Critics Poll' ou 'Readers Poll', year INT, category TEXT, winner TEXT, rank INT, points INT)

documents(id, source_id, title TEXT, author TEXT, doc_type TEXT -- article|review|poll|interview|wiki|blindfold,
          published_on DATE, year INT, issue TEXT, language TEXT)

artists(id, name TEXT, instrument TEXT, birth_year INT, death_year INT, origin TEXT)

sources(id, kind TEXT, name TEXT)

Jointures : reviews.document_id = documents.id ; documents.source_id = sources.id ; polls.document_id = documents.id.
""".strip()
