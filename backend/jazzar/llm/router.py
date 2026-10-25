"""Routeur : classe la question et extrait les filtres exacts, avec un modèle petit et rapide.

Routes :
- lookup    : fait simple vérifiable (note d'un album, date, lauréat d'un poll) -> recherche hybride k petit + modèle small
- semantic  : question ouverte sur le corpus -> recherche hybride + modèle large, effort moyen
- synthesis : synthèse historique / comparative longue -> recherche élargie + modèle large, effort élevé
- bi        : question quantitative (moyennes, évolutions, comptages) -> Text-to-SQL
- clarify   : question ambiguë -> demande de précision
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from jazzar.llm.client import LLMUnavailable, get_llm
from jazzar.retrieval.hybrid import SearchFilters

ROUTER_SYSTEM = """Tu es le routeur de Jazzar, un moteur de recherche sur 90 ans d'archives de presse jazz
(critiques d'albums notées sur 5 étoiles, articles, interviews, résultats des Critics/Readers Polls) et
sur un corpus encyclopédique ouvert.

Classe la question et extrais les filtres EXACTS qu'elle contient. Règles :
- "lookup" : un fait précis (note d'un album, label, année, lauréat d'un poll, personnel d'une session).
- "semantic" : question ouverte qui demande de lire et résumer quelques sources.
- "synthesis" : évolution dans le temps, comparaison large, "résume la critique de X sur 20 ans", dossier.
- "bi" : la réponse est un chiffre, une moyenne, un classement, une tendance ou un graphique calculés sur les métadonnées.
- "clarify" : impossible de savoir de quoi on parle (entité ambiguë sans contexte).
- year_from / year_to : uniquement si la question borne explicitement une période (une décennie = ses 10 ans).
- doc_types : parmi review, article, poll, interview, wiki, blindfold, issue ; vide si non précisé.
- keywords : 3 à 8 termes de recherche plein-texte EN ANGLAIS (noms propres, titres, termes de jazz), sans mots vides.
- lang : langue de la question (fr, en, ...).
Ne réponds jamais à la question elle-même."""


class RouteDecision(BaseModel):
    route: Literal["lookup", "semantic", "synthesis", "bi", "clarify"]
    lang: str = Field(description="Code langue de la question, ex. fr ou en")
    keywords: list[str] = Field(default_factory=list, description="Termes de recherche en anglais")
    year_from: int | None = None
    year_to: int | None = None
    doc_types: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list, description="Critiques/auteurs explicitement nommés")
    rationale: str = Field(description="Une phrase expliquant le choix de route")

    def filters(self) -> SearchFilters:
        return SearchFilters(
            year_from=self.year_from,
            year_to=self.year_to,
            doc_types=[d for d in self.doc_types if d],
            authors=self.authors,
        )


def heuristic_route(question: str) -> RouteDecision:
    """Repli sans LLM : heuristiques simples pour garder le service debout."""
    import re

    q = question.lower()
    years = [int(y) for y in re.findall(r"\b(19[3-9]\d|20[0-2]\d)\b", q)]
    decades = re.findall(r"\b(19[3-9]0|20[0-2]0)s\b|années (19[3-9]0|20[0-2]0)", q)
    year_from = min(years) if years else None
    year_to = max(years) if years else None
    for d in decades:
        dec = int(next(x for x in d if x))
        year_from, year_to = dec, dec + 9
    bi_words = ("moyenne", "average", "évolution", "evolution", "combien", "how many", "graphique", "chart", "tendance", "trend", "classement", "ranking", "pourcentage")
    route = "bi" if any(w in q for w in bi_words) else ("synthesis" if len(q) > 160 or "résume" in q or "summarize" in q else "lookup")
    words = [w for w in re.findall(r"[a-zA-Zà-ÿ'’]+", question) if len(w) > 3][:8]
    lang = "fr" if re.search(r"\b(quel|quelle|qui|quand|combien|est|les|des|dans)\b", q) else "en"
    return RouteDecision(route=route, lang=lang, keywords=words, year_from=year_from, year_to=year_to, rationale="heuristique (LLM indisponible)")


async def route_question(question: str, trace_id: str | None = None) -> tuple[RouteDecision, float, bool]:
    """Retourne (décision, coût, via_llm)."""
    llm = get_llm()
    if not llm.available:
        return heuristic_route(question), 0.0, False
    try:
        decision, cost = await llm.parse(
            purpose="route",
            system=ROUTER_SYSTEM,
            messages=[{"role": "user", "content": question}],
            output_format=RouteDecision,
            effort="low",
            max_tokens=800,
            trace_id=trace_id,
        )
        return decision, cost, True
    except LLMUnavailable:
        return heuristic_route(question), 0.0, False
    except Exception as exc:  # noqa: BLE001 - un routeur en panne ne doit pas bloquer la réponse
        from jazzar.logging import get_logger

        get_logger(__name__).warning("router.failed", error=str(exc))
        return heuristic_route(question), 0.0, False
