from unittest.mock import MagicMock
from backend.nl_search import resolve_search_query, translate_natural_language_query


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
    model.generate_content.return_value.text = "not a valid query!!"

    sql, params = resolve_search_query("something weird", model=model)

    assert sql == "(name ILIKE %s OR oracle_text ILIKE %s)"
    assert params == ["%something weird%", "%something weird%"]


def test_resolve_search_query_falls_back_when_model_call_raises():
    model = MagicMock()
    model.generate_content.side_effect = RuntimeError("API down")

    sql, params = resolve_search_query("anything", model=model)

    assert sql == "(name ILIKE %s OR oracle_text ILIKE %s)"
    assert params == ["%anything%", "%anything%"]
