import pytest

from jazzar.bi.engine import MAX_ROWS, SQLValidationError, validate_sql


def test_select_gets_limit():
    assert f"LIMIT {MAX_ROWS}" in validate_sql("SELECT genre, AVG(rating) FROM reviews GROUP BY genre")


def test_limit_is_capped():
    assert "LIMIT 500" in validate_sql("SELECT * FROM polls LIMIT 100000")


def test_cte_allowed():
    validate_sql("WITH r AS (SELECT * FROM reviews WHERE rating >= 4) SELECT artist, count(*) FROM r GROUP BY artist")


@pytest.mark.parametrize("bad", [
    "DELETE FROM reviews",
    "UPDATE reviews SET rating = 5",
    "SELECT * FROM llm_calls",
    "SELECT * FROM reviews; DROP TABLE reviews",
    "DROP TABLE reviews",
    "SELECT pg_sleep(10) FROM queries",
])
def test_rejects_dangerous(bad):
    with pytest.raises(SQLValidationError):
        validate_sql(bad)
