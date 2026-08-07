from unittest.mock import MagicMock

import pytest

from backend import nl_search
from backend.nl_search import resolve_search_query, translate_natural_language_query


@pytest.fixture(autouse=True)
def clear_translation_cache():
    nl_search._translation_cache.clear()
    yield
    nl_search._translation_cache.clear()


def test_translate_natural_language_query_returns_stripped_model_text():
    model = MagicMock()
    model.generate_content.return_value.text = "  cmc<=3 t:legendary o:draw  \n"

    result = translate_natural_language_query("cheap legendary draw cards", model=model)

    assert result == "cmc<=3 t:legendary o:draw"


def test_resolve_search_query_parses_valid_translation():
    model = MagicMock()
    model.generate_content.return_value.text = "cmc<=3"

    sql, params = resolve_search_query("cheap stuff", model=model)

    assert sql == "cmc <= %s"
    assert params == [3.0]


def test_resolve_search_query_falls_back_on_invalid_translation():
    model = MagicMock()
    model.generate_content.return_value.text = "xyz:bad"  # unrecognized prefix, triggers QueryParseError

    sql, params = resolve_search_query("something weird", model=model)

    assert sql == "(name ILIKE %s OR oracle_text ILIKE %s)"
    assert params == ["%something weird%", "%something weird%"]


def test_resolve_search_query_falls_back_when_model_call_raises():
    model = MagicMock()
    model.generate_content.side_effect = RuntimeError("API down")

    sql, params = resolve_search_query("anything", model=model)

    assert sql == "(name ILIKE %s OR oracle_text ILIKE %s)"
    assert params == ["%anything%", "%anything%"]


def test_translate_natural_language_query_caches_repeat_requests():
    model = MagicMock()
    model.generate_content.return_value.text = "cmc<=3"

    first = translate_natural_language_query("cheap stuff", model=model)
    second = translate_natural_language_query("cheap stuff", model=model)

    assert first == second == "cmc<=3"
    model.generate_content.assert_called_once()


def test_translate_natural_language_query_cache_is_case_and_whitespace_insensitive():
    model = MagicMock()
    model.generate_content.return_value.text = "cmc<=3"

    translate_natural_language_query("Cheap Stuff", model=model)
    translate_natural_language_query("  cheap stuff  ", model=model)

    model.generate_content.assert_called_once()


def test_resolve_search_query_parses_multi_word_bare_name_translation():
    """Regression test: multi-word card names (bare tokens with no special syntax)
    should parse correctly, not fall back."""
    model = MagicMock()
    model.generate_content.return_value.text = "Lightning Bolt"

    sql, params = resolve_search_query("find me lightning bolt", model=model)

    assert sql == "name ILIKE %s AND name ILIKE %s"
    assert params == ["%Lightning%", "%Bolt%"]
