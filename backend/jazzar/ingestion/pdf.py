"""Extraction de texte depuis des PDFs (numéros de magazine scannés + OCR, ou PDF natifs).

Stratégie : PyMuPDF lit la couche texte page par page, bloc par bloc (respect des colonnes).
Si une page n'a pas de couche texte (scan brut), on le signale ; l'OCR externe
(ocrmypdf / tesseract) est à lancer en amont.
"""

from __future__ import annotations

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


def extract_pdf(path: Path, *, clean: bool = True) -> PdfExtract:
    doc = fitz.open(path)
    out = PdfExtract(path=path, metadata={k: v for k, v in (doc.metadata or {}).items() if v})
    for i, page in enumerate(doc, start=1):
        blocks = page.get_text("blocks")
        # Tri colonne approximative (x arrondi) puis position verticale.
        blocks.sort(key=lambda b: (round(b[0] / 50), b[1]))
        raw = "\n\n".join(b[4] for b in blocks if b[4].strip())
        text = clean_ocr(raw) if clean else raw
        out.pages.append(PdfPage(number=i, text=text, has_text_layer=len(text.strip()) > 20))
    doc.close()
    return out
