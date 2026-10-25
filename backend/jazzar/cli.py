"""CLI d'administration : `uv run jazzar --help`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from jazzar.config import get_settings
from jazzar.logging import configure_logging

app = typer.Typer(help="Jazzar — administration (base, ingestion, évaluation, cache).", no_args_is_help=True)
db_app = typer.Typer(help="Base de données")
ingest_app = typer.Typer(help="Ingestion de corpus")
eval_app = typer.Typer(help="Évaluation (golden set)")
cache_app = typer.Typer(help="Cache sémantique")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(eval_app, name="eval")
app.add_typer(cache_app, name="cache")


@app.callback()
def _init() -> None:
    configure_logging()


@db_app.command("init")
def db_init() -> None:
    """Crée extensions, tables et index."""
    from jazzar.db import init_schema

    asyncio.run(init_schema())
    typer.echo("Schéma initialisé.")


async def _ingest(kind: str, name: str, docs, license: str | None = None, url: str | None = None) -> None:
    from jazzar.db import get_session, init_schema
    from jazzar.ingestion.service import IngestStats, get_or_create_source, ingest_document

    await init_schema()
    stats = IngestStats()
    async with get_session() as session:
        source = await get_or_create_source(session, kind, name, license=license, url=url)
        await session.commit()
        if hasattr(docs, "__aiter__"):
            async for raw in docs:
                await ingest_document(session, source, raw, stats)
                await session.commit()
        else:
            for raw in docs:
                await ingest_document(session, source, raw, stats)
                await session.commit()
    typer.echo(f"{kind}: {stats.documents} documents, {stats.chunks} chunks, {stats.skipped_duplicates} doublons ignorés, "
               f"{stats.near_duplicate_chunks} chunks quasi-dupliqués écartés.")


@ingest_app.command("samples")
def ingest_samples() -> None:
    """Ingère le corpus d'exemple (data/samples)."""
    from jazzar.ingestion.markdown_source import iter_markdown

    s = get_settings()
    asyncio.run(_ingest("sample", "Corpus d'exemple Jazzar", iter_markdown(s.samples_dir), license="illustratif"))


@ingest_app.command("local")
def ingest_local(directory: Path = typer.Argument(None, help="Dossier de fichiers .md (défaut : data/raw/local)")) -> None:
    """Ingère des notes/articles Markdown locaux."""
    from jazzar.ingestion.markdown_source import iter_markdown

    d = directory or (get_settings().data_dir / "raw" / "local")
    asyncio.run(_ingest("local", f"Corpus local ({d.name})", iter_markdown(d)))


@ingest_app.command("wikipedia")
def ingest_wikipedia(limit: int = typer.Option(60, help="Nombre max d'articles"), titles: list[str] = typer.Option(None, "--title", "-t"),
                     lang: str = "en") -> None:
    """Ingère des articles Wikipedia (corpus ouvert, CC BY-SA 4.0)."""
    from jazzar.ingestion.wikipedia_source import SEED_TITLES, fetch_many

    todo = (titles or SEED_TITLES)[:limit]
    asyncio.run(_ingest("wikipedia", f"Wikipedia ({lang})", fetch_many(todo, lang), license="CC BY-SA 4.0",
                        url=f"https://{lang}.wikipedia.org"))


@ingest_app.command("pdfs")
def ingest_pdfs(directory: Path = typer.Argument(None, help="Dossier de PDFs (défaut : data/raw/downbeat puis data/raw/local)")) -> None:
    """Ingère les PDFs (numéros DownBeat ou documents locaux)."""
    from jazzar.ingestion.pdf_source import iter_pdfs

    s = get_settings()
    targets = [(directory, "local")] if directory else [(s.data_dir / "raw" / "downbeat", "downbeat"), (s.data_dir / "raw" / "local", "local")]
    for d, kind in targets:
        if not d.exists():
            continue
        n = len(list(d.rglob("*.pdf")))
        if n == 0:
            typer.echo(f"{d}: aucun PDF.")
            continue
        typer.echo(f"{d}: {n} PDF(s)")
        name = "DownBeat (abonnement personnel)" if kind == "downbeat" else f"PDF locaux ({d.name})"
        asyncio.run(_ingest(kind, name, iter_pdfs(d, kind), license="usage privé"))


@eval_app.command("run")
def eval_run(only: list[str] = typer.Option(None, "--only", "-o", help="Identifiants de cas"), lang: str = "fr") -> None:
    """Rejoue le golden set et affiche les agrégats."""
    from jazzar.evals.runner import run_golden

    run = asyncio.run(run_golden(only=only or None, lang=lang))
    typer.echo(json.dumps(run.aggregate, indent=2, ensure_ascii=False))
    for c in run.per_case:
        mark = "✔" if c["passed"] else "✘"
        typer.echo(f"{mark} {c['id']:<9} {c['type']:<20} route={c['route']!s:<16} faith={c['faithfulness']:.2f} {c['question'][:70]}")
    typer.echo(f"GATES {'PASSED' if run.passed_gates else 'FAILED'} — coût {run.cost_usd:.4f} $")
    raise typer.Exit(code=0 if run.passed_gates else 1)


@cache_app.command("clear")
def cache_clear() -> None:
    from jazzar.llm.cache import get_cache

    n = asyncio.run(get_cache().clear())
    typer.echo(f"{n} clés supprimées.")


@app.command("ask")
def ask(question: str, lang: str = "fr", no_cache: bool = False) -> None:
    """Pose une question en ligne de commande (flux)."""
    from jazzar.db import get_session
    from jazzar.llm.answer import answer_stream

    async def _run():
        async with get_session() as session:
            async for ev in answer_stream(session, question, lang=lang, use_cache=not no_cache):
                if ev["type"] == "token":
                    typer.echo(ev["text"], nl=False)
                elif ev["type"] in ("route", "cached", "notice"):
                    typer.secho(f"\n[{ev['type']}] " + json.dumps({k: v for k, v in ev.items() if k != 'type'}, ensure_ascii=False, default=str), fg="yellow")
                elif ev["type"] == "sources":
                    typer.secho(f"[sources] {len(ev['hits'])} extraits", fg="cyan")
                elif ev["type"] == "done":
                    typer.secho(f"\n\n[done] route={ev['route']} latency={ev['latency_ms']}ms cost=${ev['cost_usd']:.4f} citations={len(ev['citations'])}", fg="green")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
