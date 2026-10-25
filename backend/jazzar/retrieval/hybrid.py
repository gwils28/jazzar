"""Recherche hybride : vecteurs (pgvector, cosinus) + plein-texte (tsvector) fusionnés par RRF,
avec filtres exacts (années, types de document, auteurs, sources).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from jazzar.config import get_settings
from jazzar.ingestion.embeddings import get_embedder


@dataclass
class SearchFilters:
    year_from: int | None = None
    year_to: int | None = None
    doc_types: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    source_kinds: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.year_from or self.year_to or self.doc_types or self.authors or self.source_kinds)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v}


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    title: str
    doc_type: str
    text: str
    score: float
    author: str | None = None
    published_on: date | None = None
    year: int | None = None
    issue: str | None = None
    page: int | None = None
    source_kind: str | None = None
    source_name: str | None = None
    url: str | None = None
    file_path: str | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published_on"] = self.published_on.isoformat() if self.published_on else None
        return d


_BASE_SELECT = """
SELECT c.id AS chunk_id, c.document_id, c.page, c.text,
       d.title, d.author, d.doc_type, d.published_on, d.year, d.issue, d.url, d.file_path,
       s.kind AS source_kind, s.name AS source_name
FROM chunks c
JOIN documents d ON d.id = c.document_id
JOIN sources s ON s.id = d.source_id
"""


def _where(filters: SearchFilters, params: dict) -> str:
    clauses = []
    if filters.year_from:
        clauses.append("d.year >= :year_from")
        params["year_from"] = filters.year_from
    if filters.year_to:
        clauses.append("d.year <= :year_to")
        params["year_to"] = filters.year_to
    if filters.doc_types:
        clauses.append("d.doc_type = ANY(:doc_types)")
        params["doc_types"] = filters.doc_types
    if filters.authors:
        clauses.append("d.author ILIKE ANY(:authors)")
        params["authors"] = [f"%{a}%" for a in filters.authors]
    if filters.source_kinds:
        clauses.append("s.kind = ANY(:source_kinds)")
        params["source_kinds"] = filters.source_kinds
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def _row_to_hit(row, score: float) -> Hit:
    return Hit(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        title=row.title,
        doc_type=row.doc_type,
        text=row.text,
        score=score,
        author=row.author,
        published_on=row.published_on,
        year=row.year,
        issue=row.issue,
        page=row.page,
        source_kind=row.source_kind,
        source_name=row.source_name,
        url=row.url,
        file_path=row.file_path,
    )


async def vector_search(session: AsyncSession, embedding: list[float], filters: SearchFilters, k: int) -> list[Hit]:
    params: dict = {"k": k, "emb": str(embedding)}
    where = _where(filters, params)
    q = sql(
        _BASE_SELECT.replace("s.kind AS source_kind, s.name AS source_name", "s.kind AS source_kind, s.name AS source_name, 1 - (c.embedding <=> CAST(:emb AS vector)) AS sim")
        + where
        + (" AND" if where else " WHERE")
        + " c.embedding IS NOT NULL ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :k"
    )
    rows = (await session.execute(q, params)).all()
    hits = []
    for rank, row in enumerate(rows, start=1):
        h = _row_to_hit(row, float(row.sim))
        h.vector_rank = rank
        hits.append(h)
    return hits


_KW_SQL = (
    _BASE_SELECT.replace(
        "s.kind AS source_kind, s.name AS source_name",
        "s.kind AS source_kind, s.name AS source_name, ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) AS rank",
    )
)


async def keyword_search(session: AsyncSession, query: str, filters: SearchFilters, k: int) -> list[Hit]:
    """Plein-texte Postgres. Première passe : tous les termes (websearch_to_tsquery, accepte guillemets,
    OR, -mot). Si rien ne remonte, seconde passe en OU logique entre les termes, classée par ts_rank_cd.
    C'est aussi le chemin fail-open sans LLM."""
    import re

    async def run(q: str) -> list:
        params: dict = {"k": k, "q": q}
        where = _where(filters, params)
        stmt = sql(_KW_SQL + where + (" AND" if where else " WHERE")
                   + " c.tsv @@ websearch_to_tsquery('english', :q) ORDER BY rank DESC LIMIT :k")
        return (await session.execute(stmt, params)).all()

    rows = await run(query)
    if not rows:
        terms = [w for w in re.findall(r"[\w'’-]+", query) if len(w) > 2]
        if len(terms) > 1:
            rows = await run(" OR ".join(terms))
    hits = []
    for rank, row in enumerate(rows, start=1):
        h = _row_to_hit(row, float(row.rank))
        h.keyword_rank = rank
        hits.append(h)
    return hits


def _rrf(vector_hits: list[Hit], keyword_hits: list[Hit], k: int = 60) -> list[Hit]:
    merged: dict[str, Hit] = {}
    for hits, attr in ((vector_hits, "vector_rank"), (keyword_hits, "keyword_rank")):
        for h in hits:
            rank = getattr(h, attr) or 1
            if h.chunk_id in merged:
                merged[h.chunk_id].score += 1.0 / (k + rank)
                setattr(merged[h.chunk_id], attr, rank)
            else:
                h.score = 1.0 / (k + rank)
                merged[h.chunk_id] = h
    return sorted(merged.values(), key=lambda h: h.score, reverse=True)


def _diversify(hits: list[Hit], max_per_doc: int = 3) -> list[Hit]:
    per_doc: dict[str, int] = {}
    out = []
    for h in hits:
        n = per_doc.get(h.document_id, 0)
        if n >= max_per_doc:
            continue
        per_doc[h.document_id] = n + 1
        out.append(h)
    return out


async def hybrid_search(
    session: AsyncSession,
    query: str,
    *,
    keywords: str | None = None,
    filters: SearchFilters | None = None,
    top_k: int | None = None,
) -> list[Hit]:
    """Recherche hybride. `keywords` : requête plein-texte (souvent traduite en anglais par le routeur)."""
    s = get_settings()
    filters = filters or SearchFilters()
    top_k = top_k or s.retrieval_top_k
    embedding = await get_embedder().aencode_one(query)
    vec = await vector_search(session, embedding, filters, s.retrieval_vector_candidates)
    kw = await keyword_search(session, keywords or query, filters, s.retrieval_keyword_candidates)
    return _diversify(_rrf(vec, kw))[:top_k]
