"""Routes HTTP de Jazzar."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi import Query as Q
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sse_starlette.sse import EventSourceResponse

from jazzar.agents.dossier import schedule_dossier
from jazzar.api.schemas import AskRequest, BIRequest, DossierRequest, FeedbackRequest, SearchRequest
from jazzar.bi import engine as bi
from jazzar.config import get_settings
from jazzar.db import get_session
from jazzar.llm.answer import answer_stream
from jazzar.llm.cache import get_cache
from jazzar.llm.client import LLMUnavailable, get_llm
from jazzar.models import Chunk, Document, Dossier, EvalRun, LLMCall, Query, Review, Source
from jazzar.retrieval.hybrid import SearchFilters, hybrid_search, keyword_search
from jazzar.text import BACKEND as TEXT_BACKEND

router = APIRouter()


def _filters(f) -> SearchFilters:
    return SearchFilters(year_from=f.year_from, year_to=f.year_to, doc_types=f.doc_types, authors=f.authors, source_kinds=f.source_kinds)


# ---- Santé & statut ------------------------------------------------------------------------------
@router.get("/health")
async def health():
    llm = get_llm()
    cache_ok = await get_cache().ping()
    async with get_session() as session:
        n_docs = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
        n_chunks = (await session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    s = get_settings()
    return {
        "status": "ok",
        "llm_available": llm.available,
        "models": {"large": s.model_large, "small": s.model_small},
        "embedding_model": s.embedding_model,
        "text_backend": TEXT_BACKEND,
        "redis": cache_ok,
        "documents": n_docs,
        "chunks": n_chunks,
    }


@router.get("/stats")
async def stats():
    async with get_session() as session:
        by_source = (await session.execute(
            select(Source.kind, Source.name, func.count(Document.id)).join(Document, Document.source_id == Source.id, isouter=True)
            .group_by(Source.kind, Source.name))).all()
        by_type = (await session.execute(select(Document.doc_type, func.count()).group_by(Document.doc_type))).all()
        years = (await session.execute(select(func.min(Document.year), func.max(Document.year)))).one()
        n_reviews = (await session.execute(select(func.count()).select_from(Review))).scalar_one()
        n_chunks = (await session.execute(select(func.count()).select_from(Chunk))).scalar_one()
        cost = (await session.execute(select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0), func.count(LLMCall.id)))).one()
        by_purpose = (await session.execute(
            select(LLMCall.purpose, func.count(), func.sum(LLMCall.cost_usd), func.avg(LLMCall.latency_ms),
                   func.sum(LLMCall.cache_read_tokens), func.sum(LLMCall.input_tokens))
            .group_by(LLMCall.purpose).order_by(desc(func.sum(LLMCall.cost_usd))))).all()
        queries = (await session.execute(
            select(func.count(Query.id), func.avg(Query.latency_ms),
                   func.sum(func.cast(Query.cached, func.coalesce(0, 0).type)) if False else func.count(Query.id).filter(Query.cached.is_(True)),
                   func.count(Query.id).filter(Query.feedback == 1), func.count(Query.id).filter(Query.feedback == -1)))).one()
        routes = (await session.execute(select(Query.route, func.count()).group_by(Query.route))).all()
        p95 = (await session.execute(select(func.percentile_cont(0.95).within_group(Query.latency_ms)))).scalar_one()
    return {
        "corpus": {
            "sources": [{"kind": k, "name": n, "documents": c} for k, n, c in by_source],
            "doc_types": {t: c for t, c in by_type},
            "year_min": years[0], "year_max": years[1], "reviews": n_reviews, "chunks": n_chunks,
        },
        "llm": {
            "total_cost_usd": round(float(cost[0]), 4), "calls": cost[1],
            "by_purpose": [{"purpose": p, "calls": c, "cost_usd": round(float(s or 0), 4), "avg_latency_ms": int(l or 0),
                            "cache_read_tokens": int(cr or 0), "input_tokens": int(it or 0)} for p, c, s, l, cr, it in by_purpose],
        },
        "queries": {"total": queries[0], "avg_latency_ms": int(queries[1] or 0), "p95_latency_ms": int(p95 or 0),
                    "cached": queries[2], "thumbs_up": queries[3], "thumbs_down": queries[4],
                    "routes": {r: c for r, c in routes}},
    }


# ---- Questions / réponses (SSE) --------------------------------------------------------------------
@router.post("/ask")
async def ask(req: AskRequest):
    async def gen():
        async with get_session() as session:
            try:
                async for ev in answer_stream(session, req.question, lang=req.lang, filters=_filters(req.filters), use_cache=req.use_cache):
                    yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False, default=str)}
            except Exception as exc:  # noqa: BLE001
                yield {"event": "error", "data": json.dumps({"type": "error", "message": str(exc)})}

    return EventSourceResponse(gen())


@router.post("/feedback")
async def feedback(req: FeedbackRequest):
    async with get_session() as session:
        q = (await session.execute(select(Query).where(Query.trace_id == req.trace_id))).scalar_one_or_none()
        if not q:
            raise HTTPException(404, "trace inconnue")
        q.feedback = req.score
        q.feedback_comment = req.comment
        await session.commit()
    return {"ok": True}


@router.get("/queries")
async def recent_queries(limit: int = Q(20, le=100)):
    async with get_session() as session:
        rows = (await session.execute(select(Query).order_by(desc(Query.created_at)).limit(limit))).scalars().all()
    return [{"trace_id": r.trace_id, "question": r.question, "route": r.route, "cached": r.cached, "latency_ms": r.latency_ms,
             "cost_usd": r.cost_usd, "feedback": r.feedback, "created_at": r.created_at, "lang": r.lang} for r in rows]


# ---- Recherche brute -------------------------------------------------------------------------------
@router.post("/search")
async def search(req: SearchRequest):
    async with get_session() as session:
        if req.mode == "keyword":
            hits = await keyword_search(session, req.query, _filters(req.filters), req.top_k)
        else:
            hits = await hybrid_search(session, req.query, filters=_filters(req.filters), top_k=req.top_k)
    return {"hits": [h.to_dict() for h in hits]}


# ---- Documents -------------------------------------------------------------------------------------
@router.get("/documents")
async def list_documents(limit: int = Q(50, le=500), offset: int = 0, doc_type: str | None = None, source_kind: str | None = None, q: str | None = None):
    async with get_session() as session:
        stmt = select(Document, Source.kind, Source.name, func.count(Chunk.id)).join(Source).join(Chunk, isouter=True)
        if doc_type:
            stmt = stmt.where(Document.doc_type == doc_type)
        if source_kind:
            stmt = stmt.where(Source.kind == source_kind)
        if q:
            stmt = stmt.where(Document.title.ilike(f"%{q}%"))
        stmt = stmt.group_by(Document.id, Source.kind, Source.name).order_by(Document.year.desc().nullslast(), Document.title).limit(limit).offset(offset)
        rows = (await session.execute(stmt)).all()
    return [{"id": d.id, "title": d.title, "author": d.author, "doc_type": d.doc_type, "published_on": d.published_on, "year": d.year,
             "issue": d.issue, "language": d.language, "url": d.url, "source_kind": k, "source_name": n, "chunks": c,
             "page_count": d.meta.get("page_count")} for d, k, n, c in rows]


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    async with get_session() as session:
        d = await session.get(Document, doc_id)
        if not d:
            raise HTTPException(404)
        src = await session.get(Source, d.source_id)
        chunks = (await session.execute(select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.ordinal))).scalars().all()
        reviews = (await session.execute(select(Review).where(Review.document_id == doc_id))).scalars().all()
    return {"id": d.id, "title": d.title, "author": d.author, "doc_type": d.doc_type, "published_on": d.published_on, "year": d.year,
            "issue": d.issue, "url": d.url, "file_path": d.file_path, "meta": d.meta, "source_kind": src.kind if src else None,
            "source_name": src.name if src else None, "has_pdf": bool(d.file_path and d.file_path.lower().endswith(".pdf")),
            "chunks": [{"id": c.id, "ordinal": c.ordinal, "page": c.page, "text": c.text} for c in chunks],
            "reviews": [{"album_title": r.album_title, "artist": r.artist, "label": r.label, "release_year": r.release_year,
                         "rating": float(r.rating) if r.rating is not None else None, "genre": r.genre} for r in reviews]}


@router.get("/documents/{doc_id}/pdf")
async def get_document_pdf(doc_id: str, page: int | None = None):
    """Sert le PDF source (lien cliquable vers la page citée via #page=N côté navigateur)."""
    async with get_session() as session:
        d = await session.get(Document, doc_id)
    if not d or not d.file_path or not d.file_path.lower().endswith(".pdf"):
        raise HTTPException(404, "pas de PDF pour ce document")
    path = Path(d.file_path)
    data_root = get_settings().data_dir.resolve()
    if not path.resolve().is_relative_to(data_root) or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


# ---- Dossiers --------------------------------------------------------------------------------------
@router.post("/dossiers", status_code=202)
async def create_dossier(req: DossierRequest):
    import uuid

    if not get_llm().available:
        raise HTTPException(503, "Service IA indisponible : configurez ANTHROPIC_API_KEY.")
    async with get_session() as session:
        d = Dossier(trace_id=str(uuid.uuid4()), brief=req.brief, lang=req.lang, status="queued")
        session.add(d)
        await session.commit()
        await session.refresh(d)
        dossier_id = d.id
    schedule_dossier(dossier_id)
    return {"id": dossier_id, "status": "queued"}


def _dossier_out(d: Dossier, full: bool) -> dict:
    out = {"id": d.id, "created_at": d.created_at, "updated_at": d.updated_at, "brief": d.brief, "lang": d.lang, "status": d.status,
           "title": d.title, "cost_usd": d.cost_usd, "error": d.error, "n_citations": len(d.citations or []),
           "steps": d.steps if full else (d.steps or [])[-3:]}
    if full:
        out.update({"plan": d.plan, "markdown": d.markdown, "citations": d.citations})
    return out


@router.get("/dossiers")
async def list_dossiers(limit: int = Q(30, le=200)):
    async with get_session() as session:
        rows = (await session.execute(select(Dossier).order_by(desc(Dossier.created_at)).limit(limit))).scalars().all()
    return [_dossier_out(d, False) for d in rows]


@router.get("/dossiers/{dossier_id}")
async def get_dossier(dossier_id: str):
    async with get_session() as session:
        d = await session.get(Dossier, dossier_id)
    if not d:
        raise HTTPException(404)
    return _dossier_out(d, True)


# ---- BI --------------------------------------------------------------------------------------------
@router.post("/bi/analyze")
async def bi_analyze(req: BIRequest):
    try:
        return await bi.analyze(req.question, req.lang)
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except bi.SQLValidationError as exc:
        raise HTTPException(400, f"SQL rejeté : {exc}") from exc


@router.get("/bi/schema")
async def bi_schema():
    from jazzar.models import BI_SCHEMA_DESCRIPTION

    return {"schema": BI_SCHEMA_DESCRIPTION}


# ---- Evals -----------------------------------------------------------------------------------------
@router.get("/evals")
async def list_evals(limit: int = Q(20, le=100)):
    async with get_session() as session:
        rows = (await session.execute(select(EvalRun).order_by(desc(EvalRun.created_at)).limit(limit))).scalars().all()
    return [{"id": r.id, "created_at": r.created_at, "system_version": r.system_version, "golden_set": r.golden_set,
             "aggregate": r.aggregate, "passed_gates": r.passed_gates, "cost_usd": r.cost_usd} for r in rows]


@router.get("/evals/{run_id}")
async def get_eval(run_id: str):
    async with get_session() as session:
        r = await session.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404)
    return {"id": r.id, "created_at": r.created_at, "system_version": r.system_version, "golden_set": r.golden_set,
            "aggregate": r.aggregate, "per_case": r.per_case, "passed_gates": r.passed_gates, "cost_usd": r.cost_usd}


@router.post("/evals/run", status_code=202)
async def trigger_eval(only: list[str] | None = None):
    import asyncio

    from jazzar.evals.runner import run_golden

    if not get_llm().available:
        raise HTTPException(503, "Service IA indisponible.")
    task = asyncio.create_task(run_golden(only=only))
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    return {"status": "started"}


_bg: set = set()


# ---- Cache -----------------------------------------------------------------------------------------
@router.delete("/cache")
async def clear_cache():
    n = await get_cache().clear()
    return {"cleared": n}
