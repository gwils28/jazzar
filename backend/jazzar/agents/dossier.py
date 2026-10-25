"""Le Documentaliste Autonome : génération de dossiers de recherche sourcés par une équipe d'agents.

Pipeline (chaque étape est journalisée dans dossiers.steps) :
1. Planificateur  (sortie structurée) : titre, sections, questions de recherche par section.
2. Chercheur      (tool runner, boucle agentique) : interroge l'archive (recherche hybride, lecture de document,
                   métadonnées SQL) autant que nécessaire, section par section, et rend des notes sourcées.
3. Rédacteur      (flux long) : rédige le dossier en Markdown, chaque affirmation citée [S-n] (identifiants d'extraits).
4. Critique       (sortie structurée) : vérifie que chaque [S-n] existe et étaye l'affirmation ; corrige ou supprime.

Toutes les citations renvoient à des chunks réels (chunk_id), ce qui permet des liens cliquables vers la source.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from jazzar.bi.engine import SQLValidationError, run_sql, validate_sql
from jazzar.config import get_settings
from jazzar.db import get_session
from jazzar.llm.client import LLMRefused, LLMUnavailable, get_llm
from jazzar.logging import get_logger
from jazzar.models import Chunk, Document, Dossier
from jazzar.retrieval.hybrid import Hit, SearchFilters, hybrid_search

log = get_logger(__name__)


# --------------------------------------------------------------------------------------------------
# 1. Planificateur
# --------------------------------------------------------------------------------------------------
class Section(BaseModel):
    heading: str
    goal: str = Field(description="Ce que la section doit établir, en une phrase")
    research_questions: list[str] = Field(description="2 à 4 questions précises à poser à l'archive")


class DossierPlan(BaseModel):
    title: str
    audience: str = Field(description="Pour qui est le dossier et ce qu'il doit lui permettre de faire")
    period_from: int | None = None
    period_to: int | None = None
    sections: list[Section] = Field(description="4 à 8 sections, de l'introduction à la conclusion")
    needs_quantitative: bool = Field(description="Vrai si des chiffres (notes moyennes, comptages) renforceraient le dossier")


PLANNER_SYSTEM = """Tu es le planificateur d'une équipe de documentalistes travaillant sur une archive de presse jazz
(critiques notées, articles, interviews, polls) et un corpus encyclopédique. Transforme la commande en plan de
dossier : titre, public, période, 4 à 8 sections avec pour chacune 2 à 4 questions de recherche concrètes et
cherchables (noms d'artistes, albums, événements, termes précis). Les questions doivent être formulées en anglais
(langue du corpus) même si la commande est en français. Ne rédige pas le dossier."""


# --------------------------------------------------------------------------------------------------
# 2. Chercheur (tool runner)
# --------------------------------------------------------------------------------------------------
RESEARCHER_SYSTEM = """Tu es le chercheur d'une équipe de documentalistes jazz. Pour la section qui t'est confiée,
interroge l'archive avec les outils fournis jusqu'à disposer de preuves suffisantes, puis rends des NOTES DE
RECHERCHE sourcées.

Méthode :
- Commence par search_archive sur chaque question de recherche ; reformule et affine (synonymes, noms propres,
  années) si les résultats sont faibles. Utilise les filtres d'années quand la section porte sur une période.
- Lis un document en entier avec read_document quand un extrait est prometteur mais tronqué.
- Utilise query_metadata pour les chiffres (notes moyennes, comptages, lauréats de polls).
- 4 à 10 appels d'outils suffisent en général ; arrête-toi quand les nouvelles recherches n'apportent plus rien.

Format de sortie (texte) : une liste de faits, chacun suivi de son identifiant d'extrait exact [S-xxxx] tel que
retourné par les outils. N'écris AUCUN fait sans identifiant. Signale explicitement ce que l'archive ne couvre pas."""

WRITER_SYSTEM = """Tu es le rédacteur d'un dossier de recherche destiné à des professionnels (labels, documentaristes,
programmateurs). Tu disposes du plan et des notes de recherche sourcées de chaque section.

RÈGLES
- Chaque affirmation factuelle porte sa référence [S-xxxx] copiée EXACTEMENT depuis les notes. Aucune autre source.
- N'ajoute aucun fait absent des notes, même s'il te semble évident. Si une section manque de matière, dis-le en
  une phrase plutôt que de combler.
- Les extraits marqués « source=sample » proviennent d'un corpus d'exemple : signale-le une fois dans le dossier.
- Markdown : titre de niveau 1, sections de niveau 2 selon le plan, paragraphes développés (le dossier doit être
  substantiel : vise 1 500 à 3 000 mots selon la matière), listes quand c'est utile, pas de section « Sources »
  (l'interface la génère).
- Langue : celle demandée."""


class CritiqueIssue(BaseModel):
    location: str = Field(description="Citation du passage concerné (quelques mots)")
    problem: str
    action: str = Field(description="corrigé | supprimé | reformulé")


class Critique(BaseModel):
    issues: list[CritiqueIssue]
    revised_markdown: str = Field(description="Le dossier complet corrigé")
    confidence: float = Field(ge=0, le=1, description="Confiance globale dans la fidélité aux sources")


CRITIC_SYSTEM = """Tu es le relecteur-vérificateur. Tu reçois un dossier Markdown et les extraits sources référencés
[S-xxxx]. Vérifie chaque affirmation :
- une référence [S-xxxx] absente de la liste des extraits -> supprime l'affirmation ou remplace par une référence valide ;
- une affirmation non étayée par son extrait (date, nom, note différents) -> corrige d'après l'extrait ou supprime ;
- une affirmation sans référence -> ajoute la bonne référence si elle existe, sinon supprime.
Ne reformule pas le style au-delà du nécessaire. Rends le dossier complet corrigé et la liste des problèmes."""


class ResearchContext:
    """Garde la trace de tous les extraits vus par le chercheur, indexés par identifiant court [S-xxxx]."""

    def __init__(self) -> None:
        self.hits: dict[str, Hit] = {}
        self.calls: list[dict] = []

    def register(self, hits: list[Hit]) -> list[dict]:
        out = []
        for h in hits:
            sid = "S-" + h.chunk_id[:8]
            self.hits[sid] = h
            when = h.published_on.isoformat() if h.published_on else (str(h.year) if h.year else "n.d.")
            out.append({"id": sid, "title": h.title, "author": h.author, "date": when, "type": h.doc_type,
                        "source": h.source_kind, "page": h.page, "text": h.text})
        return out


def _make_tools(ctx: ResearchContext, default_filters: SearchFilters):
    from anthropic import beta_async_tool

    @beta_async_tool
    async def search_archive(query: str, year_from: int | None = None, year_to: int | None = None, doc_types: list[str] | None = None) -> str:
        """Recherche hybride (sémantique + mots-clés) dans l'archive jazz. Retourne jusqu'à 8 extraits avec leur identifiant [S-xxxx].

        Args:
            query: Question ou mots-clés, en anglais de préférence (langue du corpus).
            year_from: Année de début (inclusive), optionnelle.
            year_to: Année de fin (inclusive), optionnelle.
            doc_types: Types de documents : review, article, poll, interview, wiki, issue. Optionnel.
        """
        filters = SearchFilters(year_from=year_from or default_filters.year_from, year_to=year_to or default_filters.year_to,
                                doc_types=doc_types or [])
        async with get_session() as session:
            hits = await hybrid_search(session, query, filters=filters, top_k=8)
            if not hits and not filters.is_empty():
                hits = await hybrid_search(session, query, filters=SearchFilters(), top_k=8)
        ctx.calls.append({"tool": "search_archive", "query": query, "n": len(hits)})
        return json.dumps(ctx.register(hits), ensure_ascii=False)

    @beta_async_tool
    async def read_document(source_id: str) -> str:
        """Lit le document complet (toutes ses pages/extraits) d'où provient un extrait [S-xxxx].

        Args:
            source_id: Identifiant d'extrait, ex. S-1a2b3c4d.
        """
        h = ctx.hits.get(source_id.strip())
        if not h:
            return json.dumps({"error": f"identifiant inconnu {source_id}"})
        async with get_session() as session:
            rows = (await session.execute(
                select(Chunk).where(Chunk.document_id == h.document_id).order_by(Chunk.ordinal)
            )).scalars().all()
            doc = await session.get(Document, h.document_id)
        parts = []
        for c in rows[:40]:
            hit = Hit(chunk_id=c.id, document_id=c.document_id, title=doc.title if doc else h.title, doc_type=h.doc_type,
                      text=c.text, score=0, author=h.author, published_on=h.published_on, year=h.year, issue=h.issue,
                      page=c.page, source_kind=h.source_kind)
            parts.extend(ctx.register([hit]))
        ctx.calls.append({"tool": "read_document", "source_id": source_id, "chunks": len(parts)})
        return json.dumps({"title": doc.title if doc else h.title, "chunks": parts}, ensure_ascii=False)

    @beta_async_tool
    async def query_metadata(sql_query: str) -> str:
        """Exécute une requête SQL SELECT en lecture seule sur les métadonnées (reviews, polls, documents, artists).

        Args:
            sql_query: Requête PostgreSQL SELECT. Schéma : reviews(album_title, artist, label, release_year, review_year, rating 0-5, genre, reviewer), polls(poll_name, year, category, winner, rank), documents(title, author, doc_type, year), artists(name, instrument).
        """
        try:
            safe = validate_sql(sql_query)
            columns, rows = await run_sql(safe)
        except (SQLValidationError, Exception) as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})
        ctx.calls.append({"tool": "query_metadata", "sql": safe, "rows": len(rows)})
        return json.dumps({"columns": columns, "rows": rows[:100], "note": "Les chiffres issus de 'sample' sont illustratifs."}, ensure_ascii=False)

    return [search_archive, read_document, query_metadata]


async def _research_section(ctx: ResearchContext, plan: DossierPlan, section: Section, filters: SearchFilters, trace_id: str) -> tuple[str, float]:
    llm = get_llm()
    settings = get_settings()
    tools = _make_tools(ctx, filters)
    brief = (f"Dossier : {plan.title}\nPériode : {plan.period_from or '?'}–{plan.period_to or '?'}\n"
             f"Section : {section.heading}\nObjectif : {section.goal}\nQuestions :\n- " + "\n- ".join(section.research_questions))
    runner = llm.client.beta.messages.tool_runner(
        model=settings.model_large,
        max_tokens=8000,
        system=[{"type": "text", "text": RESEARCHER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        tools=tools,
        messages=[{"role": "user", "content": brief}],
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        max_iterations=14,
    )
    cost = 0.0
    last = None
    t0 = time.perf_counter()
    async for message in runner:
        last = message
        cost += await llm._record("dossier:research", settings.model_large, message, int((time.perf_counter() - t0) * 1000), trace_id,
                                  meta={"section": section.heading})
        t0 = time.perf_counter()
    notes = "".join(b.text for b in (last.content if last else []) if b.type == "text")
    return notes, cost


# --------------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------------
async def _update(dossier_id: str, **fields: Any) -> None:
    async with get_session() as session:
        d = await session.get(Dossier, dossier_id)
        if d is None:
            return
        for k, v in fields.items():
            setattr(d, k, v)
        await session.commit()


async def _log_step(dossier_id: str, steps: list[dict], step: str, **data: Any) -> None:
    steps.append({"step": step, "at": time.time(), **data})
    await _update(dossier_id, steps=list(steps))


async def run_dossier(dossier_id: str) -> None:
    """Exécute le pipeline complet pour un dossier existant (statut queued)."""
    llm = get_llm()
    settings = get_settings()
    steps: list[dict] = []
    total_cost = 0.0
    async with get_session() as session:
        d = await session.get(Dossier, dossier_id)
        if d is None:
            return
        brief, lang, trace_id = d.brief, d.lang, d.trace_id
    try:
        if not llm.available:
            raise LLMUnavailable("Service IA indisponible : impossible de générer un dossier.")

        # 1. Plan
        await _update(dossier_id, status="planning")
        plan, cost = await llm.parse(purpose="dossier:plan", system=PLANNER_SYSTEM,
                                     messages=[{"role": "user", "content": f"Langue du dossier : {lang}\nCommande : {brief}"}],
                                     output_format=DossierPlan, model=settings.model_large, effort="medium", max_tokens=4000, trace_id=trace_id)
        total_cost += cost
        await _update(dossier_id, plan=plan.model_dump(), title=plan.title, cost_usd=total_cost)
        await _log_step(dossier_id, steps, "plan", sections=[s.heading for s in plan.sections])

        # 2. Recherche (sections en parallèle, concurrence limitée)
        await _update(dossier_id, status="researching")
        ctx = ResearchContext()
        filters = SearchFilters(year_from=plan.period_from, year_to=plan.period_to)
        sem = asyncio.Semaphore(3)

        async def research(section: Section) -> tuple[Section, str, float]:
            async with sem:
                notes, c = await _research_section(ctx, plan, section, filters, trace_id)
                await _log_step(dossier_id, steps, "research", section=section.heading, chars=len(notes))
                return section, notes, c

        results = await asyncio.gather(*(research(s) for s in plan.sections))
        for _, _, c in results:
            total_cost += c
        await _update(dossier_id, cost_usd=total_cost)
        await _log_step(dossier_id, steps, "research_done", tool_calls=len(ctx.calls), unique_sources=len(ctx.hits))

        # 3. Rédaction
        await _update(dossier_id, status="writing")
        notes_block = "\n\n".join(f"## {s.heading}\nObjectif : {s.goal}\n\nNOTES :\n{n}" for s, n, _ in results)
        sources_block = "\n\n".join(
            f"[{sid}] {h.title} — {h.author or ''} — {h.published_on or h.year or 'n.d.'} — type={h.doc_type} — source={h.source_kind}\n{h.text}"
            for sid, h in ctx.hits.items()
        )
        writer_input = (f"Langue : {lang}\n\nPLAN\n{plan.model_dump_json(indent=1)}\n\nNOTES DE RECHERCHE PAR SECTION\n{notes_block}\n\n"
                        f"EXTRAITS SOURCES (pour vérification des références)\n{sources_block}")
        parts: list[str] = []
        async with llm.stream(purpose="dossier:write", system=WRITER_SYSTEM, messages=[{"role": "user", "content": writer_input}],
                              model=settings.model_large, effort="high", max_tokens=32000, trace_id=trace_id) as stream:
            async for text in stream.text_stream:
                parts.append(text)
        total_cost += getattr(stream, "_jazzar_cost", 0.0)
        draft = "".join(parts)
        await _update(dossier_id, markdown=draft, cost_usd=total_cost)
        await _log_step(dossier_id, steps, "draft", words=len(draft.split()))

        # 4. Critique
        await _update(dossier_id, status="reviewing")
        try:
            critique, cost = await llm.parse(
                purpose="dossier:critic", system=CRITIC_SYSTEM,
                messages=[{"role": "user", "content": f"DOSSIER\n{draft}\n\nEXTRAITS SOURCES\n{sources_block}"}],
                output_format=Critique, model=settings.model_large, effort="high", max_tokens=40000, trace_id=trace_id)
            total_cost += cost
            final_md = critique.revised_markdown or draft
            await _log_step(dossier_id, steps, "critique", issues=[i.model_dump() for i in critique.issues], confidence=critique.confidence)
        except (LLMRefused, Exception) as exc:  # noqa: BLE001
            log.warning("dossier.critic_failed", error=str(exc))
            final_md = draft
            await _log_step(dossier_id, steps, "critique_skipped", error=str(exc))

        # Citations finales = identifiants effectivement présents dans le texte
        import re

        used = sorted(set(re.findall(r"\[(S-[0-9a-f]{8})\]", final_md)))
        citations = [{"id": sid, **ctx.hits[sid].to_dict()} for sid in used if sid in ctx.hits]
        await _update(dossier_id, status="done", markdown=final_md, citations=citations, cost_usd=round(total_cost, 6))
        await _log_step(dossier_id, steps, "done", citations=len(citations), cost_usd=round(total_cost, 4))
    except Exception as exc:
        log.exception("dossier.failed", dossier_id=dossier_id)
        await _update(dossier_id, status="failed", error=str(exc), cost_usd=round(total_cost, 6))
        await _log_step(dossier_id, steps, "failed", error=str(exc))


_running: set[asyncio.Task] = set()


def schedule_dossier(dossier_id: str) -> None:
    task = asyncio.create_task(run_dossier(dossier_id))
    _running.add(task)
    task.add_done_callback(_running.discard)
