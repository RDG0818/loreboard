from backend.query_parser import QueryParseError, parse_query


def test_parse_cmc_comparison():
    sql, params = parse_query("cmc<=3")
    assert sql == "cmc <= %s"
    assert params == [3.0]


def test_parse_type_filter():
    sql, params = parse_query("t:legendary")
    assert sql == "type_line ILIKE %s"
    assert params == ["%legendary%"]


def test_parse_oracle_text_filter():
    sql, params = parse_query("o:draw")
    assert sql == "oracle_text ILIKE %s"
    assert params == ["%draw%"]


def test_parse_colors_filter_uppercases_letters():
    sql, params = parse_query("c:wu")
    assert sql == "colors @> %s"
    assert params == [["W", "U"]]


def test_parse_color_identity_filter():
    sql, params = parse_query("id:g")
    assert sql == "color_identity @> %s"
    assert params == [["G"]]


def test_parse_format_legality_filter():
    sql, params = parse_query("f:commander")
    assert sql == "legalities ->> %s = 'legal'"
    assert params == ["commander"]


def test_parse_bare_word_matches_name():
    sql, params = parse_query("Bolt")
    assert sql == "name ILIKE %s"
    assert params == ["%Bolt%"]


def test_parse_combines_multiple_tokens_with_and():
    sql, params = parse_query("cmc<=3 t:legendary o:draw")
    assert sql == "cmc <= %s AND type_line ILIKE %s AND oracle_text ILIKE %s"
    assert params == [3.0, "%legendary%", "%draw%"]


def test_parse_empty_query_raises():
    try:
        parse_query("   ")
        assert False, "expected QueryParseError"
    except QueryParseError:
        pass


def test_parse_unrecognized_operator_raises():
    try:
        parse_query("xyz:something")
        assert False, "expected QueryParseError"
    except QueryParseError:
        pass
