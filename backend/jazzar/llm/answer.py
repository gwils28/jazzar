"""Orchestration d'une question : routage -> cache sémantique -> recherche hybride -> génération citée.

Produit un flux d'événements (SSE côté API) :
  {"type": "route", ...} {"type": "sources", ...} {"type": "token", "text": ...}
  {"type": "cached", ...} {"type": "done", ...} {"type": "error", ...}

Garanties :
- Zéro affirmation sans source : le modèle ne peut citer que les extraits fournis, numérotés [n].
- Fail-open : sans LLM (clé absente, API en panne) on renvoie les extraits de la recherche par mots-clés.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from jazzar.config import get_settings
from jazzar.ingestion.embeddings import get_embedder
from jazzar.llm.cache import get_cache
from jazzar.llm.client import LLMUnavailable, get_llm
from jazzar.llm.router import route_question
from jazzar.logging import get_logger
from jazzar.models import Query
from jazzar.retrieval.hybrid import Hit, SearchFilters, hybrid_search, keyword_search

log = get_logger(__name__)

ANSWER_SYSTEM = """Tu es Jazzar, l'assistant de recherche d'une archive de presse jazz (critiques d'albums notées
sur 5 étoiles, articles, interviews, résultats de polls) complétée par un corpus encyclopédique ouvert.
Tes lecteurs sont des historiens, journalistes, producteurs et programmateurs : l'exactitude prime.

RÈGLES ABSOLUES
1. Tu réponds UNIQUEMENT à partir des extraits fournis, numérotés [1], [2], ... Chaque affirmation factuelle
   (nom, date, label, note, personnel, citation) porte sa référence entre crochets immédiatement après, ex. « ... en 1959 [2]. »
2. Si les extraits ne permettent pas de répondre, dis-le explicitement en une phrase, précise ce qui manque,
   et ne complète JAMAIS avec tes connaissances générales. Si la question repose sur une prémisse fausse ou
   invérifiable (événement inventé, détail inconnaissable), signale-le au lieu d'inventer.
3. Les notes (étoiles), dates et noms sont recopiés tels qu'ils apparaissent dans la source. Ne les arrondis pas, ne les devines pas.
4. Les extraits dont la source est « sample » sont un corpus d'exemple illustratif : signale-le si tu t'appuies dessus pour une note ou un classement.
5. Réponds dans la langue demandée (indiquée dans la requête). Les titres d'œuvres et citations restent dans leur langue d'origine.

STYLE
- Concis et précis. Markdown léger : paragraphes courts, listes si plusieurs éléments, pas de titre de niveau 1.
- Ne reproduis pas la liste des sources à la fin : l'interface l'affiche à partir de tes références [n]."""


def _format_sources(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        meta = [h.title]
        if h.author:
            meta.append(h.author)
        if h.published_on:
            meta.append(h.published_on.isoformat())
        elif h.year:
            meta.append(str(h.year))
        if h.issue:
            meta.append(h.issue)
        if h.page:
            meta.append(f"p. {h.page}")
        meta.append(f"type={h.doc_type}")
        meta.append(f"source={h.source_kind}")
        blocks.append(f"[{i}] " + " — ".join(meta) + "\n" + h.text.strip())
    return "\n\n".join(blocks)


def _used_citations(answer: str, hits: list[Hit]) -> list[dict]:
    nums = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", answer) if 0 < int(n) <= len(hits)})
    return [{"n": n, **hits[n - 1].to_dict()} for n in nums]


_ROUTE_PARAMS = {
    # route: (modèle, effort, top_k, max_tokens)
    "lookup": ("small", "low", 6, 1500),
    "semantic": ("large", "medium", 10, 4000),
    "synthesis": ("large", "high", 16, 8000),
}


async def answer_stream(
    session: AsyncSession,
    question: str,
    *,
    lang: str | None = None,
    filters: SearchFilters | None = None,
    use_cache: bool = True,
) -> AsyncIterator[dict]:
    settings = get_settings()
    llm = get_llm()
    trace_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    total_cost = 0.0

    decision, cost, via_llm = await route_question(question, trace_id)
    total_cost += cost
    if filters and not filters.is_empty():
        # Les filtres explicites de l'UI priment sur ceux déduits par le routeur.
        merged = decision.filters()
        merged.year_from = filters.year_from or merged.year_from
        merged.year_to = filters.year_to or merged.year_to
        merged.doc_types = filters.doc_types or merged.doc_types
        merged.authors = filters.authors or merged.authors
        merged.source_kinds = filters.source_kinds
    else:
        merged = decision.filters()
    answer_lang = lang or decision.lang or "fr"
    yield {"type": "route", "trace_id": trace_id, "route": decision.route, "via_llm": via_llm,
           "filters": merged.to_dict(), "keywords": decision.keywords, "rationale": decision.rationale}

    if decision.route == "bi":
        # Délégué au moteur BI par l'API ; on signale simplement la redirection.
        yield {"type": "redirect", "to": "bi", "trace_id": trace_id}
        return
    if decision.route == "clarify":
        msg = ("Peux-tu préciser de quel artiste, album ou période tu parles ?" if answer_lang.startswith("fr")
               else "Could you specify which artist, album or period you mean?")
        yield {"type": "token", "text": msg}
        yield {"type": "done", "trace_id": trace_id, "route": "clarify", "citations": [], "cost_usd": total_cost,
               "latency_ms": int((time.perf_counter() - t0) * 1000), "cached": False}
        return

    embedding = await get_embedder().aencode_one(question)

    # --- Cache sémantique ---
    cache = get_cache()
    if use_cache:
        hit = await cache.lookup(question, embedding, merged.to_dict(), answer_lang)
        if hit:
            yield {"type": "sources", "hits": [c for c in hit["citations"]]}
            yield {"type": "cached", "similarity": hit["similarity"], "cached_question": hit["cached_question"]}
            yield {"type": "token", "text": hit["answer"]}
            latency = int((time.perf_counter() - t0) * 1000)
            await _save_query(session, trace_id, question, answer_lang, "cache", merged, hit["answer"], hit["citations"], True, latency, total_cost)
            yield {"type": "done", "trace_id": trace_id, "route": "cache", "citations": hit["citations"],
                   "cost_usd": total_cost, "latency_ms": latency, "cached": True}
            return

    # --- Retrieval ---
    size, effort, top_k, max_tokens = _ROUTE_PARAMS.get(decision.route, _ROUTE_PARAMS["semantic"])
    keywords = " ".join(decision.keywords) if decision.keywords else None
    hits = await hybrid_search(session, question, keywords=keywords, filters=merged, top_k=top_k)
    if not hits and not merged.is_empty():
        # Filtres trop stricts : on retente sans pour signaler ce qui existe.
        hits = await hybrid_search(session, question, keywords=keywords, filters=SearchFilters(), top_k=top_k)
        yield {"type": "notice", "text": "Aucune source dans la période/filtre demandé ; résultats élargis."}
    yield {"type": "sources", "hits": [h.to_dict() | {"n": i + 1} for i, h in enumerate(hits)]}

    if not hits:
        msg = ("Je n'ai trouvé aucune source dans l'archive pour cette question." if answer_lang.startswith("fr")
               else "I found no source in the archive for this question.")
        yield {"type": "token", "text": msg}
        latency = int((time.perf_counter() - t0) * 1000)
        await _save_query(session, trace_id, question, answer_lang, "no_sources", merged, msg, [], False, latency, total_cost)
        yield {"type": "done", "trace_id": trace_id, "route": "no_sources", "citations": [], "cost_usd": total_cost,
               "latency_ms": latency, "cached": False}
        return

    # --- Génération ---
    if not llm.available:
        async for ev in _fail_open(session, trace_id, question, answer_lang, merged, hits, t0, total_cost, reason="llm_unavailable"):
            yield ev
        return

    model = settings.model_large if size == "large" else settings.model_small
    lang_name = {"fr": "français", "en": "English"}.get(answer_lang[:2], answer_lang)
    user_content = (
        f"Langue de réponse : {lang_name}\nRoute : {decision.route}\n\n"
        f"EXTRAITS\n{_format_sources(hits)}\n\nQUESTION\n{question}"
    )
    answer_parts: list[str] = []
    try:
        async with llm.stream(
            purpose=f"answer:{decision.route}",
            system=ANSWER_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
            model=model,
            effort=effort,
            max_tokens=max_tokens,
            trace_id=trace_id,
        ) as stream:
            async for text in stream.text_stream:
                answer_parts.append(text)
                yield {"type": "token", "text": text}
        total_cost += getattr(stream, "_jazzar_cost", 0.0)
        final = getattr(stream, "_jazzar_final", None)
        if final is not None and final.stop_reason == "refusal":
            yield {"type": "notice", "text": "Le modèle a décliné cette requête."}
    except (LLMUnavailable, anthropic.AuthenticationError, anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        log.warning("answer.llm_failed", error=str(exc))
        if not answer_parts:
            async for ev in _fail_open(session, trace_id, question, answer_lang, merged, hits, t0, total_cost, reason=type(exc).__name__):
                yield ev
            return

    answer = "".join(answer_parts)
    citations = _used_citations(answer, hits)
    latency = int((time.perf_counter() - t0) * 1000)
    if use_cache and citations:
        await cache.store(question, embedding, merged.to_dict(), answer_lang, answer, citations, decision.route)
    await _save_query(session, trace_id, question, answer_lang, decision.route, merged, answer, citations, False, latency, total_cost)
    yield {"type": "done", "trace_id": trace_id, "route": decision.route, "citations": citations,
           "cost_usd": round(total_cost, 6), "latency_ms": latency, "cached": False, "model": model}


async def _fail_open(session, trace_id, question, lang, filters, hits, t0, cost, *, reason: str) -> AsyncIterator[dict]:
    """Chemin dégradé : pas de synthèse, on expose directement les meilleurs extraits."""
    if not hits:
        hits = await keyword_search(session, question, filters, 8)
    intro = ("Synthèse indisponible (service IA hors ligne). Voici les extraits les plus pertinents de l'archive :"
             if lang.startswith("fr") else
             "Synthesis unavailable (AI service offline). Here are the most relevant archive excerpts:")
    lines = [intro, ""]
    for i, h in enumerate(hits, start=1):
        when = h.published_on.isoformat() if h.published_on else (str(h.year) if h.year else "")
        meta = ", ".join(x for x in (when, f"p. {h.page}" if h.page else "") if x)
        lines.append(f"- **{h.title}**" + (f" ({meta})" if meta else "") + f" [{i}] — {h.text[:300].strip()}…")
    text = "\n".join(lines)
    yield {"type": "notice", "text": f"fail-open: {reason}"}
    yield {"type": "token", "text": text}
    citations = [{"n": i + 1, **h.to_dict()} for i, h in enumerate(hits)]
    latency = int((time.perf_counter() - t0) * 1000)
    await _save_query(session, trace_id, question, lang, "fallback_keyword", filters, text, citations, False, latency, cost)
    yield {"type": "done", "trace_id": trace_id, "route": "fallback_keyword", "citations": citations,
           "cost_usd": cost, "latency_ms": latency, "cached": False}


async def _save_query(session: AsyncSession, trace_id, question, lang, route, filters: SearchFilters, answer, citations, cached, latency, cost) -> None:
    try:
        session.add(Query(trace_id=trace_id, question=question, lang=lang, route=route, filters=filters.to_dict(),
                          answer=answer, citations=citations, cached=cached, latency_ms=latency, cost_usd=cost))
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("query.save_failed", error=str(exc))
        await session.rollback()
