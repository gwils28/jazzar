"""Extraction de texte depuis des PDFs (numéros de magazine scannés + OCR, ou PDF natifs).

Stratégie : PyMuPDF lit la couche texte page par page, bloc par bloc (respect des colonnes).
Si une page n'a pas de couche texte (scan brut), on le signale ; l'OCR externe
(ocrmypdf / tesseract) est à lancer en amont.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from jazzar.text import clean_ocr


@dataclass
class PdfPage:
    number: int  # 1-indexé
    text: str
    has_text_layer: bool


@dataclass
class PdfExtract:
    path: Path
    pages: list[PdfPage] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text_coverage(self) -> float:
        if not self.pages:
            return 0.0
        return sum(1 for p in self.pages if p.has_text_layer) / len(self.pages)


# Folio de magazine : « 12 DOWNBEAT JULY 2025 » ou « JULY 2025 DOWNBEAT 12 ». Sur les pages de pub
# (image pleine page) c'est le seul texte natif ; sans ce filtre on indexe un chunk vide de sens par page.
_RE_CAPS_WORD = re.compile(r"[A-Z][A-Z'’.&-]*")
_RE_YEAR = re.compile(r"(?:19|20)\d{2}")
_RE_PAGE_NO = re.compile(r"\d{1,3}")
# En dessous, une page ne contient qu'un crédit photo ou un titre orphelin : pas de quoi citer.
MIN_PAGE_CHARS = 40


def _is_folio(line: str) -> bool:
    toks = line.split()
    if not 3 <= len(toks) <= 7:
        return False
    page_no = toks[0] if _RE_PAGE_NO.fullmatch(toks[0]) else (toks[-1] if _RE_PAGE_NO.fullmatch(toks[-1]) else None)
    if page_no is None:
        return False
    rest = [t for t in toks if t is not page_no]
    years = [t for t in rest if _RE_YEAR.fullmatch(t)]
    words = [t for t in rest if _RE_CAPS_WORD.fullmatch(t)]
    return len(years) == 1 and len(words) == len(rest) - 1


def strip_folios(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _is_folio(line.strip())).strip()


def extract_pdf(path: Path, *, clean: bool = True) -> PdfExtract:
    doc = fitz.open(path)
    out = PdfExtract(path=path, metadata={k: v for k, v in (doc.metadata or {}).items() if v})
    for i, page in enumerate(doc, start=1):
        blocks = page.get_text("blocks")
        # Tri colonne approximative (x arrondi) puis position verticale.
        blocks.sort(key=lambda b: (round(b[0] / 50), b[1]))
        raw = "\n\n".join(b[4] for b in blocks if b[4].strip())
        text = strip_folios(clean_ocr(raw) if clean else raw)
        out.pages.append(PdfPage(number=i, text=text, has_text_layer=len(text) >= MIN_PAGE_CHARS))
    doc.close()
    return out
