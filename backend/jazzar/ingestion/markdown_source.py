"""Source Markdown + en-tête YAML (corpus d'exemple et notes locales)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from jazzar.ingestion.service import RawDocument, RawPage, RawPollResult, RawReview
from jazzar.text import clean_ocr


def parse_markdown(path: Path) -> RawDocument | None:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    body = body.strip()
    if not body or not meta.get("title"):
        return None

    published = meta.get("published_on")
    if isinstance(published, str):
        published = date.fromisoformat(published)

    reviews = []
    if rv := meta.get("review"):
        reviews.append(
            RawReview(
                album_title=rv["album_title"],
                artist=rv["artist"],
                label=rv.get("label"),
                release_year=rv.get("release_year"),
                genre=rv.get("genre"),
                rating=rv.get("rating"),
                reviewer=meta.get("author"),
            )
        )
    polls = []
    if pl := meta.get("poll"):
        for r in pl.get("results", []):
            polls.append(
                RawPollResult(
                    poll_name=pl["poll_name"],
                    year=int(pl["year"]),
                    category=r["category"],
                    winner=r["winner"],
                    rank=int(r.get("rank", 1)),
                    points=r.get("points"),
                )
            )

    return RawDocument(
        title=meta["title"],
        doc_type=meta.get("doc_type", "article"),
        pages=[RawPage(number=None, text=clean_ocr(body))],
        author=meta.get("author"),
        published_on=published,
        issue=meta.get("issue"),
        language=meta.get("language", "en"),
        file_path=str(path),
        meta={k: v for k, v in meta.items() if k not in {"review", "poll"}},
        reviews=reviews,
        polls=polls,
    )


def iter_markdown(directory: Path):
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        doc = parse_markdown(path)
        if doc:
            yield doc
