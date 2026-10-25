"""Primitives texte : nettoyage OCR, estimation de tokens, chunking, simhash.

Utilise l'extension Rust `jazzar_text` (rust/jazzar-text, PyO3) si elle est installée,
sinon une implémentation Python équivalente. L'interface est identique.
"""

from __future__ import annotations

import re
import unicodedata

try:  # pragma: no cover - dépend de la compilation
    import jazzar_text as _rs

    BACKEND = "rust"
except ImportError:  # pragma: no cover
    _rs = None
    BACKEND = "python"

_RE_HYPHEN_BREAK = re.compile(r"([^\W\d_])-\s*\n\s*([a-zà-ÿ])")
_RE_SOFT_BREAK = re.compile(r"([^\n.!?:;—])\n(?!\n)[ \t]*(?=[\w«(])")
_RE_MULTI_SPACE = re.compile(r"[ \t ]{2,}")
_RE_MULTI_NL = re.compile(r"\n{3,}")
_RE_TOKEN = re.compile(r"[^\W\d_]+|\d+|[^\s\w]")


def _py_clean_ocr(text: str) -> str:
    s = unicodedata.normalize("NFKC", text)
    s = "".join(c for c in s if not unicodedata.category(c).startswith("C") or c in "\n\t")
    s = s.replace("﻿", "").replace("\r", "").replace("‘", "'").replace("’", "'")
    s = _RE_HYPHEN_BREAK.sub(r"\1\2", s)
    s = _RE_SOFT_BREAK.sub(r"\1 ", s)
    s = _RE_MULTI_SPACE.sub(" ", s)
    s = _RE_MULTI_NL.sub("\n\n", s)
    return "\n".join(line.strip() for line in s.split("\n")).strip()


def _py_estimate_tokens(text: str) -> int:
    import math

    return math.ceil(len(_RE_TOKEN.findall(text)) * 1.3)


def _split_sentences(text: str) -> list[tuple[int, int]]:
    """Fin de phrase = [.!?…] + guillemets fermants optionnels + blanc ; ou paragraphe (\\n\\n)."""
    n = len(text)
    out: list[tuple[int, int]] = []
    start = i = 0
    while i < n:
        c = text[i]
        if c in ".!?…":
            j = i + 1
            while j < n and text[j] in "»\")]'":
                j += 1
            if j >= n or text[j].isspace():
                while j < n and text[j].isspace():
                    j += 1
                out.append((start, j))
                start = i = j
                continue
        if c == "\n" and i + 1 < n and text[i + 1] == "\n":
            j = i
            while j < n and text[j].isspace():
                j += 1
            out.append((start, j))
            start = i = j
            continue
        i += 1
    if start < n:
        out.append((start, n))
    return out


def _py_chunk(text: str, target_tokens: int = 400, overlap_tokens: int = 60) -> list[tuple[int, int, str]]:
    sentences = [
        (a, b, _py_estimate_tokens(text[a:b].strip())) for a, b in _split_sentences(text) if text[a:b].strip()
    ]
    if not sentences:
        return []
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < len(sentences):
        start = sentences[i][0]
        tokens = 0
        j = i
        while j < len(sentences) and (tokens == 0 or tokens + sentences[j][2] <= target_tokens):
            tokens += sentences[j][2]
            j += 1
        end = sentences[j - 1][1]
        s = text[start:end].strip()
        if s:
            out.append((start, end, s))
        if j >= len(sentences):
            break
        back = 0
        k = j
        while k > i + 1 and back + sentences[k - 1][2] <= overlap_tokens:
            back += sentences[k - 1][2]
            k -= 1
        i = max(k, i + 1)
    return out


def _fnv1a64(b: bytes) -> int:
    h = 0xCBF29CE484222325
    for byte in b:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _py_simhash(text: str) -> int:
    words = [w.lower() for w in _RE_TOKEN.findall(text) if any(c.isalnum() for c in w)]
    if not words:
        return 0
    acc = [0] * 64
    n = len(words)
    window = min(3, n)
    for i in range(n - window + 1):
        h = _fnv1a64(" ".join(words[i : i + window]).encode())
        for b in range(64):
            acc[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if acc[b] > 0:
            out |= 1 << b
    return out


def _py_hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


clean_ocr = _rs.clean_ocr if _rs else _py_clean_ocr
estimate_tokens = _rs.estimate_tokens if _rs else _py_estimate_tokens
chunk = _rs.chunk if _rs else _py_chunk
simhash = _rs.simhash if _rs else _py_simhash
hamming = _rs.hamming if _rs else _py_hamming


def to_signed64(value: int) -> int:
    """Postgres BIGINT est signé : convertit un u64 en i64 pour le stockage."""
    return value - (1 << 64) if value >= (1 << 63) else value
