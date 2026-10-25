from jazzar import text


def test_clean_ocr_dehyphenates_and_joins_lines():
    raw = "Miles Davis plays the trum-\npet on this re-\ncord.\nThe band\nincludes Bill Evans.\n\n\n\nNew paragraph."
    out = text.clean_ocr(raw)
    assert "trumpet" in out and "record" in out
    assert "The band includes Bill Evans." in out
    assert "\n\n\n" not in out


def test_chunk_respects_target_and_overlap():
    body = " ".join(f"Sentence number {i} talks about jazz history." for i in range(120))
    chunks = text.chunk(body, 100, 20)
    assert len(chunks) > 3
    for start, end, piece in chunks:
        assert body[start:end].strip() == piece
        assert text.estimate_tokens(piece) <= 140
    # recouvrement : le début du chunk suivant est avant la fin du précédent
    assert chunks[1][0] < chunks[0][1]


def test_simhash_near_duplicates():
    a = (
        "John Coltrane recorded A Love Supreme in December 1964 for Impulse Records with his classic quartet: "
        "McCoy Tyner on piano, Jimmy Garrison on bass and Elvin Jones on drums. The four-part suite opens with "
        "Acknowledgement, continues with Resolution and Pursuance, and closes with Psalm, a wordless recitation "
        "of the poem printed on the sleeve. It remains his most devotional and most disciplined statement."
    )
    b = a.replace("December", "Dec.")  # une seule variation OCR-like
    c = (
        "Dave Brubeck's Time Out explores unusual meters such as 5/4 and 9/8 on Columbia in 1959, with Paul "
        "Desmond's Take Five riding a two-chord piano vamp and Joe Morello's restrained drum solo. Blue Rondo "
        "alternates a Turkish theme with conventional blues choruses while Eugene Wright keeps the bass honest."
    )
    near = text.hamming(text.simhash(a), text.simhash(b))
    far = text.hamming(text.simhash(a), text.simhash(c))
    assert near <= 12 and far > 16 and near < far


def test_python_and_rust_backends_agree():
    sample = "Alpha beta. Gamma delta! Epsilon? Zeta eta theta.\n\nIota kappa."
    assert text._py_chunk(sample, 8, 2) == [tuple(c) for c in text.chunk(sample, 8, 2)]
    assert text._py_simhash(sample) == text.simhash(sample)
