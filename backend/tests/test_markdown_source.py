from pathlib import Path

from jazzar.ingestion.markdown_source import iter_markdown, parse_markdown

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_parse_review_frontmatter():
    doc = parse_markdown(SAMPLES / "1959-08-kind-of-blue-review.md")
    assert doc is not None
    assert doc.doc_type == "review"
    assert doc.published_on is not None and doc.published_on.year == 1959
    assert doc.reviews[0].rating == 5.0 and doc.reviews[0].label == "Columbia"
    assert "Wynton Kelly" in doc.full_text


def test_parse_poll():
    doc = parse_markdown(SAMPLES / "1965-08-critics-poll.md")
    assert doc is not None and doc.doc_type == "poll"
    assert any(p.category == "Tenor Saxophone" and p.winner == "John Coltrane" for p in doc.polls)


def test_iter_skips_readme():
    titles = [d.title for d in iter_markdown(SAMPLES)]
    assert len(titles) >= 8 and all("README" not in t for t in titles)
