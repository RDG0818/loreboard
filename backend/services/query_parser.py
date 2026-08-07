import re

_CMC_RE = re.compile(r"^cmc(<=|>=|<|>|=)(\d+(?:\.\d+)?)$")
_TYPE_RE = re.compile(r"^t:(\S+)$")
_ORACLE_RE = re.compile(r"^o:(\S+)$")
_COLOR_RE = re.compile(r"^c:([wubrg]+)$", re.IGNORECASE)
_IDENTITY_RE = re.compile(r"^id:([wubrg]+)$", re.IGNORECASE)
_FORMAT_RE = re.compile(r"^f:(\w+)$")

_CMC_OPS = {"<=": "<=", ">=": ">=", "<": "<", ">": ">", "=": "="}


class QueryParseError(ValueError):
    pass


def parse_query(query: str) -> tuple[str, list]:
    """Parses a small subset of Scryfall's search grammar into a
    parameterized SQL WHERE fragment + params. All values are parameterized
    (never string-interpolated) — safe against SQL injection.

    Supported: cmc<=N / cmc>=N / cmc<N / cmc>N / cmc=N, t:WORD, o:WORD
    (single word only — see module docstring in the implementation plan for
    why), c:WUBRG, id:WUBRG, f:FORMAT. Bare tokens match card name.
    """
    tokens = query.strip().split()
    if not tokens:
        raise QueryParseError("empty query")

    clauses = []
    params: list = []

    for token in tokens:
        m = _CMC_RE.match(token)
        if m:
            op, value = m.groups()
            clauses.append(f"cmc {_CMC_OPS[op]} %s")
            params.append(float(value))
            continue

        m = _TYPE_RE.match(token)
        if m:
            clauses.append("type_line ILIKE %s")
            params.append(f"%{m.group(1)}%")
            continue

        m = _ORACLE_RE.match(token)
        if m:
            clauses.append("oracle_text ILIKE %s")
            params.append(f"%{m.group(1)}%")
            continue

        m = _COLOR_RE.match(token)
        if m:
            clauses.append("colors @> %s")
            params.append([c.upper() for c in m.group(1)])
            continue

        m = _IDENTITY_RE.match(token)
        if m:
            clauses.append("color_identity @> %s")
            params.append([c.upper() for c in m.group(1)])
            continue

        m = _FORMAT_RE.match(token)
        if m:
            clauses.append("legalities ->> %s = 'legal'")
            params.append(m.group(1))
            continue

        if ":" in token:
            raise QueryParseError(f"unrecognized query token: {token!r}")

        clauses.append("name ILIKE %s")
        params.append(f"%{token}%")

    return " AND ".join(clauses), params
