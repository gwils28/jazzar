"""Source PDF : numéros de magazine déposés dans data/raw/downbeat ou data/raw/local.

Un PDF = un document "issue" (on ne segmente pas encore en articles ; la page reste l'unité de
citation). Le nom de fichier est parsé pour retrouver la date quand il suit le motif
`DB25_07.pdf` (nommage des numéros DownBeat : année sur 2 chiffres + mois),
`DownBeat_1965-07-01.pdf`, `1965-07-01 ...pdf` ou contient une année.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from jazzar.ingestion.pdf import extract_pdf
from jazzar.ingestion.service import RawDocument, RawPage

_RE_DATE = re.compile(r"(19[3-9]\d|20[0-2]\d)[-_.]?(0[1-9]|1[0-2])?[-_.]?(0[1-9]|[12]\d|3[01])?")
# Numéros DownBeat tels que téléchargés : DB25_07 = juillet 2025. Le magazine existe depuis 1934,
# donc 00-33 → 20xx et 34-99 → 19xx.
_RE_DOWNBEAT_ISSUE = re.compile(r"^DB(\d{2})[-_ ]?(0[1-9]|1[0-2])(?!\d)", re.IGNORECASE)
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]


def guess_date(name: str) -> tuple[date | None, int | None]:
    m = _RE_DOWNBEAT_ISSUE.match(name)
    if m:
        yy, month = int(m.group(1)), int(m.group(2))
        year = 2000 + yy if yy < 34 else 1900 + yy
        return date(year, month, 1), year
    m = _RE_DATE.search(name)
    if not m:
        return None, None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else None
    day = int(m.group(3)) if m.group(3) else None
    if month:
        try:
            return date(year, month, day or 1), year
        except ValueError:
            return None, year
    return None, year


def pdf_to_raw(path: Path, kind: str) -> RawDocument | None:
    extract = extract_pdf(path)
    pages = [RawPage(number=p.number, text=p.text) for p in extract.pages if p.has_text_layer]
    if not pages:
        return None
    published, year = guess_date(path.stem)
    if kind == "downbeat" and published:
        # Les métadonnées des scans sont absentes ou parasites (« DB25_07.indd ») : on titre par la date.
        title = f"DownBeat — {_MONTHS[published.month - 1]} {published.year}"
    else:
        title = extract.metadata.get("title") or path.stem.replace("_", " ")
    return RawDocument(
        title=title,
        doc_type="issue" if kind == "downbeat" else "article",
        pages=pages,
        author=extract.metadata.get("author"),
        published_on=published,
        issue=path.stem if kind == "downbeat" else None,
        language="en",
        file_path=str(path),
        meta={"year": year, "page_count": extract.page_count, "text_coverage": round(extract.text_coverage, 3)},
    )


def iter_pdfs(directory: Path, kind: str):
    for path in sorted(directory.rglob("*.pdf")):
        doc = pdf_to_raw(path, kind)
        if doc:
            yield doc
