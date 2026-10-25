"""Corpus ouvert : articles Wikipedia (CC BY-SA 4.0) sur le jazz, via l'API REST.

Point d'entrée : une liste de titres (albums, artistes, mouvements) ou une catégorie.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from jazzar.ingestion.service import RawDocument, RawPage
from jazzar.text import clean_ocr

USER_AGENT = "Jazzar/0.1 (projet personnel d'archives jazz; contact: local)"

SEED_TITLES = [
    # Albums
    "Kind of Blue", "A Love Supreme", "Giant Steps", "Time Out (album)", "Mingus Ah Um", "Bitches Brew",
    "Getz/Gilberto", "Saxophone Colossus", "Blue Train (album)", "Somethin' Else (Cannonball Adderley album)",
    "Head Hunters", "The Köln Concert", "Free Jazz: A Collective Improvisation", "Ascension (John Coltrane album)",
    "The Shape of Jazz to Come", "Brilliant Corners", "Moanin' (Art Blakey album)", "Maiden Voyage (Herbie Hancock album)",
    "Speak No Evil", "Out to Lunch!", "Unit Structures", "Heavy Weather (album)", "Return to Forever (album)",
    "Birth of the Cool", "Sketches of Spain", "Ellington at Newport", "The Black Saint and the Sinner Lady",
    "Song for My Father (album)", "Waltz for Debby (Bill Evans album)", "Sunday at the Village Vanguard",
    # Artistes
    "Miles Davis", "John Coltrane", "Charlie Parker", "Thelonious Monk", "Bill Evans", "Charles Mingus",
    "Ornette Coleman", "Cecil Taylor", "Wayne Shorter", "Herbie Hancock", "Chick Corea", "Art Blakey",
    "Sonny Rollins", "Dave Brubeck", "Duke Ellington", "Louis Armstrong", "Dizzy Gillespie", "Keith Jarrett",
    "Cannonball Adderley", "Eric Dolphy", "Albert Ayler", "Sun Ra", "Weather Report", "Return to Forever",
    "Elvin Jones", "McCoy Tyner", "Paul Chambers", "Jimmy Cobb", "Wynton Kelly", "Astrud Gilberto",
    # Mouvements / institutions
    "Bebop", "Hard bop", "Free jazz", "Modal jazz", "Cool jazz", "Jazz fusion", "Bossa nova", "Big band",
    "Association for the Advancement of Creative Musicians", "DownBeat", "Blue Note Records", "Impulse! Records",
    "Chicago jazz", "Jazz Messengers", "Second Great Quintet", "Jazz in Chicago",
]


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|table|sup|figure|aside)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)</(p|h[1-6]|li|div|section)>", "\n\n", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\[\s*(edit|modifier)\s*\]", "", text)
    import html as html_mod

    return clean_ocr(html_mod.unescape(text))


async def fetch_article(client: httpx.AsyncClient, title: str, lang: str = "en") -> RawDocument | None:
    base = f"https://{lang}.wikipedia.org/api/rest_v1/page"
    summary = await client.get(f"{base}/summary/{title}")
    if summary.status_code != 200:
        return None
    meta = summary.json()
    html = await client.get(f"{base}/html/{meta['title']}")
    if html.status_code != 200:
        return None
    text = _html_to_text(html.text)
    # Coupe les sections de fin peu utiles au RAG.
    for marker in ("\nReferences\n", "\nSee also\n", "\nExternal links\n", "\nNotes\n", "\nBibliography\n"):
        idx = text.find(marker)
        if idx > 2000:
            text = text[:idx]
    if len(text) < 500:
        return None
    # Pages "virtuelles" de ~6000 caractères pour garder une granularité de citation.
    pages = [RawPage(number=i + 1, text=text[i * 6000 : (i + 1) * 6000]) for i in range((len(text) + 5999) // 6000)]
    return RawDocument(
        title=meta["title"],
        doc_type="wiki",
        pages=pages,
        author="Wikipedia contributors",
        published_on=None,
        issue=None,
        language=lang,
        url=meta.get("content_urls", {}).get("desktop", {}).get("page"),
        meta={"description": meta.get("description"), "license": "CC BY-SA 4.0", "revision": meta.get("revision")},
    )


async def fetch_many(titles: list[str], lang: str = "en", concurrency: int = 4):
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:

        async def one(t: str):
            async with sem:
                try:
                    return await fetch_article(client, t, lang)
                except httpx.HTTPError:
                    return None

        for coro in asyncio.as_completed([one(t) for t in titles]):
            doc = await coro
            if doc:
                yield doc
