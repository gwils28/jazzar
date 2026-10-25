"""BI as Code : question en langage naturel -> SQL (validé, lecture seule) -> données -> spécification de graphique.

Sécurité du Text-to-SQL :
- Le SQL est analysé avec sqlglot : une seule instruction, SELECT uniquement, tables dans une liste blanche.
- Exécution via le rôle Postgres `jazzar_ro` (SELECT only), statement_timeout court, LIMIT forcé.
- Le modèle ne voit que la description du schéma analytique, jamais les tables techniques.

Le graphique n'est pas du code exécuté : c'est une spécification Plotly (JSON) que le frontend rend.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

import sqlglot
from pydantic import BaseModel, Field
from sqlalchemy import text as sql

from jazzar.config import get_settings
from jazzar.db import get_ro_engine
from jazzar.llm.client import LLMRefused, LLMUnavailable, get_llm
from jazzar.logging import get_logger
from jazzar.models import BI_SCHEMA_DESCRIPTION

log = get_logger(__name__)

ALLOWED_TABLES = {"reviews", "polls", "documents", "artists", "sources"}
MAX_ROWS = 500
STATEMENT_TIMEOUT_MS = 8000

SQL_SYSTEM = f"""Tu es l'analyste data de Jazzar. Tu traduis une question de journaliste ou d'historien du jazz
en UNE requête SQL PostgreSQL en lecture seule, puis tu décris le graphique le plus parlant.

{BI_SCHEMA_DESCRIPTION}

RÈGLES
- Une seule instruction SELECT (CTE autorisées). Jamais de INSERT/UPDATE/DELETE/DDL. Pas de point-virgule final.
- Colonnes de sortie nommées clairement en snake_case (ex. year, genre, avg_rating, n_reviews).
- Toujours un ORDER BY pertinent et LIMIT {MAX_ROWS} au maximum.
- Comparaisons de texte insensibles à la casse (ILIKE ou lower()). Les genres sont déjà en minuscules.
- Si la question est impossible avec ce schéma, mets feasible=false et explique en une phrase.
- Pour les séries temporelles, agrège par year (ou par décennie : (year/10)*10 AS decade).
- chart.type : line (évolution), bar (comparaison), scatter (corrélation), table (liste), none (valeur unique).
- Note dans caveats toute limite d'interprétation (ex. échantillon petit, corpus d'exemple)."""


class ChartSpec(BaseModel):
    type: Literal["line", "bar", "scatter", "table", "none"]
    x: str | None = Field(default=None, description="Colonne pour l'axe X")
    y: list[str] = Field(default_factory=list, description="Colonnes pour l'axe Y (une série par colonne)")
    series: str | None = Field(default=None, description="Colonne catégorielle qui sépare les séries (ex. genre)")
    title: str
    x_label: str | None = None
    y_label: str | None = None


class SQLPlan(BaseModel):
    feasible: bool
    sql: str = Field(default="", description="Requête SELECT PostgreSQL")
    explanation: str = Field(description="Une ou deux phrases : ce que calcule la requête")
    chart: ChartSpec
    caveats: list[str] = Field(default_factory=list)


class SQLValidationError(ValueError):
    pass


def validate_sql(query: str) -> str:
    query = query.strip().rstrip(";")
    try:
        statements = sqlglot.parse(query, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise SQLValidationError(f"SQL invalide : {exc}") from exc
    if len(statements) != 1 or statements[0] is None:
        raise SQLValidationError("Une seule instruction autorisée.")
    stmt = statements[0]
    if not isinstance(stmt, sqlglot.exp.Select) and not (isinstance(stmt, sqlglot.exp.Union)):
        # Une CTE racine est un Select avec with ; Union pour UNION ALL
        raise SQLValidationError("Seules les requêtes SELECT sont autorisées.")
    forbidden = (sqlglot.exp.Insert, sqlglot.exp.Update, sqlglot.exp.Delete, sqlglot.exp.Drop, sqlglot.exp.Create,
                 sqlglot.exp.Alter, sqlglot.exp.Command, sqlglot.exp.Set)
    if any(isinstance(n, forbidden) for n in stmt.walk()):
        raise SQLValidationError("Instruction interdite détectée.")
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(sqlglot.exp.CTE)}
    for table in stmt.find_all(sqlglot.exp.Table):
        name = table.name.lower()
        if name and name not in ALLOWED_TABLES and name not in cte_names:
            raise SQLValidationError(f"Table non autorisée : {name}")
    # LIMIT forcé
    if not stmt.args.get("limit"):
        stmt = stmt.limit(MAX_ROWS)
    else:
        try:
            current = int(stmt.args["limit"].expression.this)
            if current > MAX_ROWS:
                stmt = stmt.limit(MAX_ROWS)
        except (AttributeError, ValueError, TypeError):
            stmt = stmt.limit(MAX_ROWS)
    return stmt.sql(dialect="postgres")


async def run_sql(query: str) -> tuple[list[str], list[list[Any]]]:
    engine = get_ro_engine()
    async with engine.connect() as conn:
        await conn.execute(sql(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        result = await conn.execute(sql(query))
        columns = list(result.keys())
        rows = [[_jsonable(v) for v in row] for row in result.fetchall()]
    return columns, rows


def _jsonable(v: Any) -> Any:
    import datetime
    import decimal

    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def build_plotly(columns: list[str], rows: list[list[Any]], chart: ChartSpec) -> dict | None:
    """Construit {data, layout} Plotly à partir des lignes. Les couleurs sont appliquées côté frontend."""
    if chart.type in ("table", "none") or not rows or not chart.x:
        return None
    idx = {c: i for i, c in enumerate(columns)}
    if chart.x not in idx:
        return None
    traces = []
    mode = {"line": "lines+markers", "scatter": "markers"}.get(chart.type)
    ptype = "bar" if chart.type == "bar" else "scatter"
    if chart.series and chart.series in idx and chart.y and chart.y[0] in idx:
        ycol = chart.y[0]
        groups: dict[Any, list] = {}
        for r in rows:
            groups.setdefault(r[idx[chart.series]], []).append(r)
        for name, grp in groups.items():
            traces.append({"type": ptype, "mode": mode, "name": str(name),
                           "x": [g[idx[chart.x]] for g in grp], "y": [g[idx[ycol]] for g in grp]})
    else:
        for ycol in [y for y in chart.y if y in idx]:
            traces.append({"type": ptype, "mode": mode, "name": ycol,
                           "x": [r[idx[chart.x]] for r in rows], "y": [r[idx[ycol]] for r in rows]})
    if not traces:
        return None
    layout = {"title": {"text": chart.title},
              "xaxis": {"title": {"text": chart.x_label or chart.x}},
              "yaxis": {"title": {"text": chart.y_label or (chart.y[0] if chart.y else "")}},
              "barmode": "group"}
    return {"data": traces, "layout": layout}


async def analyze(question: str, lang: str = "fr") -> dict:
    """Pipeline complet. Retourne un dict sérialisable (plan, sql, colonnes, lignes, figure, insight, coût)."""
    llm = get_llm()
    trace_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    if not llm.available:
        raise LLMUnavailable("Le moteur BI nécessite le service IA (Text-to-SQL).")
    settings = get_settings()
    plan, cost = await llm.parse(
        purpose="bi:sql",
        system=SQL_SYSTEM,
        messages=[{"role": "user", "content": f"Langue : {lang}\nQuestion : {question}"}],
        output_format=SQLPlan,
        model=settings.model_large,
        effort="medium",
        max_tokens=3000,
        trace_id=trace_id,
    )
    out: dict[str, Any] = {"trace_id": trace_id, "question": question, "plan": plan.model_dump(), "cost_usd": cost}
    if not plan.feasible:
        out.update({"columns": [], "rows": [], "figure": None, "insight": plan.explanation, "sql": None,
                    "latency_ms": int((time.perf_counter() - t0) * 1000)})
        return out
    try:
        safe_sql = validate_sql(plan.sql)
        columns, rows = await run_sql(safe_sql)
    except (SQLValidationError, Exception) as exc:  # noqa: BLE001
        # Une tentative de correction avec le message d'erreur.
        log.warning("bi.sql_failed", error=str(exc), sql=plan.sql)
        plan, cost2 = await llm.parse(
            purpose="bi:sql:repair",
            system=SQL_SYSTEM,
            messages=[
                {"role": "user", "content": f"Langue : {lang}\nQuestion : {question}"},
                {"role": "assistant", "content": plan.model_dump_json()},
                {"role": "user", "content": f"Cette requête a échoué : {exc}\nCorrige-la (même format de réponse)."},
            ],
            output_format=SQLPlan,
            model=settings.model_large,
            effort="medium",
            max_tokens=3000,
            trace_id=trace_id,
        )
        cost += cost2
        safe_sql = validate_sql(plan.sql)
        columns, rows = await run_sql(safe_sql)
        out["plan"] = plan.model_dump()
    figure = build_plotly(columns, rows, plan.chart)

    # Insight court rédigé à partir des données (petit modèle, effort bas).
    insight = plan.explanation
    if rows:
        preview = "\n".join(", ".join(f"{c}={v}" for c, v in zip(columns, r, strict=True)) for r in rows[:40])
        try:
            msg = await llm.complete(
                purpose="bi:insight",
                model=settings.model_small,
                effort="low",
                max_tokens=600,
                system=("Tu es data-journaliste jazz. À partir des lignes de résultat fournies, écris 2 à 4 phrases "
                        "d'analyse factuelle dans la langue demandée : tendance, extrêmes, nuance. Cite les chiffres "
                        "exacts. N'invente aucune donnée absente des lignes. Mentionne si l'échantillon est petit."),
                messages=[{"role": "user", "content": f"Langue : {lang}\nQuestion : {question}\nSQL : {safe_sql}\n"
                                                      f"Résultats ({len(rows)} lignes, 40 premières) :\n{preview}"}],
                trace_id=trace_id,
            )
            insight = "".join(b.text for b in msg.content if b.type == "text") or insight
            cost += getattr(msg, "_jazzar_cost", 0.0)
        except (LLMRefused, Exception) as exc:  # noqa: BLE001
            log.warning("bi.insight_failed", error=str(exc))
    out.update({"sql": safe_sql, "columns": columns, "rows": rows, "figure": figure, "insight": insight,
                "cost_usd": round(cost, 6), "latency_ms": int((time.perf_counter() - t0) * 1000)})
    return out
