from datetime import date

from jazzar.ingestion.pdf import strip_folios
from jazzar.ingestion.pdf_source import guess_date


def test_strip_folios_removes_running_headers_only():
    assert strip_folios("12 DOWNBEAT JULY 2025") == ""
    assert strip_folios("JULY 2025 DOWNBEAT 51\n\nOn his sophomore LP Endlessly…") == "On his sophomore LP Endlessly…"
    # Un intertitre sans numéro de page n'est pas un folio.
    assert strip_folios("CRITICS POLL 2025\n\nJazz Artist of the Year") == "CRITICS POLL 2025\n\nJazz Artist of the Year"


def test_guess_date_downbeat_issue_name():
    assert guess_date("DB25_07") == (date(2025, 7, 1), 2025)
    assert guess_date("db65-03") == (date(1965, 3, 1), 1965)
    assert guess_date("DB34_01") == (date(1934, 1, 1), 1934)


def test_guess_date_full_date_and_year_only():
    assert guess_date("DownBeat_1965-07-01") == (date(1965, 7, 1), 1965)
    assert guess_date("1958 Blindfold Test") == (None, 1958)


def test_guess_date_no_match():
    assert guess_date("notes") == (None, None)
    assert guess_date("DB25_13") == (None, None)
