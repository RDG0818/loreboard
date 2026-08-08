import psycopg2.extras

UPSERT_SQL = """
INSERT INTO cards (id, name, oracle_text, type_line, mana_cost, cmc, colors, color_identity, legalities, artist, image_uris, set_type, is_universes_beyond)
VALUES (%(id)s, %(name)s, %(oracle_text)s, %(type_line)s, %(mana_cost)s, %(cmc)s, %(colors)s, %(color_identity)s, %(legalities)s, %(artist)s, %(image_uris)s, %(set_type)s, %(is_universes_beyond)s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    oracle_text = EXCLUDED.oracle_text,
    type_line = EXCLUDED.type_line,
    mana_cost = EXCLUDED.mana_cost,
    cmc = EXCLUDED.cmc,
    colors = EXCLUDED.colors,
    color_identity = EXCLUDED.color_identity,
    legalities = EXCLUDED.legalities,
    artist = EXCLUDED.artist,
    image_uris = EXCLUDED.image_uris,
    set_type = EXCLUDED.set_type,
    is_universes_beyond = EXCLUDED.is_universes_beyond
"""

CARD_LIST_COLUMNS = "id, name, artist, image_uris, colors"


def card_row_from_json(card: dict) -> dict:
    """Maps a raw Scryfall card object (from the bulk JSONL dump) to our row
    shape. Double-faced cards store oracle text/images/colors per-face
    instead of at the top level, so fall back to the front face."""
    oracle_text = card.get("oracle_text")
    image_uris = card.get("image_uris")
    colors = card.get("colors")
    faces = card.get("card_faces") or []

    if oracle_text is None and faces:
        oracle_text = " // ".join(f.get("oracle_text", "") for f in faces).strip() or None
    if image_uris is None and faces:
        image_uris = faces[0].get("image_uris")
    if colors is None and faces:
        colors = faces[0].get("colors")

    return {
        "id": card["id"],
        "name": card["name"],
        "oracle_text": oracle_text,
        "type_line": card.get("type_line"),
        "mana_cost": card.get("mana_cost"),
        "cmc": card.get("cmc"),
        "colors": colors,
        "color_identity": card.get("color_identity"),
        "legalities": psycopg2.extras.Json(card.get("legalities") or {}),
        "artist": card.get("artist"),
        "image_uris": psycopg2.extras.Json(image_uris) if image_uris else None,
        "set_type": card.get("set_type"),
        "is_universes_beyond": "universesbeyond" in (card.get("promo_types") or []),
    }


def upsert_card(conn, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(UPSERT_SQL, row)


def iter_missing_embeddings(conn):
    """Yields (card_id, embedding_text) for every card without an embedding."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, type_line, oracle_text FROM cards WHERE embedding IS NULL")
        rows = cur.fetchall()
    for card_id, name, type_line, oracle_text in rows:
        yield card_id, f"{name}. {type_line or ''}. {oracle_text or ''}"


def set_card_embedding(conn, card_id: str, embedding: list[float]) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE cards SET embedding = %s WHERE id = %s", (embedding, card_id))


def get_card_embedding(conn, card_id: str) -> list[float] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT embedding FROM cards WHERE id = %s", (card_id,))
        row = cur.fetchone()
        return row[0] if row else None


def fetch_cards_page(
    conn, cursor: str | None, limit: int = 30, seed: str | None = None, include_all: bool = False
) -> list[dict]:
    """Cursor-paginated card feed.

    Without a seed, orders by plain `id` (stable, deterministic — used by
    callers that don't care about feed order, e.g. tooling/tests).

    With a seed, orders by `md5(id || seed)` instead: a cheap per-request
    shuffle that's still keyset-paginatable (tie-broken by id so the order is
    total). The order key is a pure function of (id, seed), so a page's last
    `id` is enough to resume — the cursor format doesn't change, we just
    recompute the same hash for the cursor row to build the WHERE clause.

    This is the extension point for feed ranking: swapping `md5(id || seed)`
    for a recommendation score (or blending the two) only touches `row_key`
    below — the keyset pagination shape and the API contract (cursor = last
    card's id) stay the same.

    Unless include_all is set, hides "off-vibe" cards by default: joke/
    playtest sets (Scryfall's set_type == 'funny', covers both silver-border
    Un-sets and official Mystery Booster Playtest cards) and Universes Beyond
    crossovers (is_universes_beyond, derived from promo_types at ingest time
    — Marvel, Final Fantasy, LOTR, etc).
    """
    where_clauses = []
    params = {"limit": limit, "seed": seed, "cursor": cursor}

    if not include_all:
        where_clauses.append("set_type IS DISTINCT FROM 'funny'")
        where_clauses.append("NOT is_universes_beyond")

    if seed is None:
        row_key = "id"
        if cursor:
            where_clauses.append("id > %(cursor)s")
    else:
        row_key = "md5(id || %(seed)s)"
        if cursor:
            cursor_key = "md5(%(cursor)s || %(seed)s)"
            where_clauses.append(f"({row_key}, id) > ({cursor_key}, %(cursor)s)")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    order_sql = f"ORDER BY {row_key}, id" if seed is not None else f"ORDER BY {row_key}"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {CARD_LIST_COLUMNS} FROM cards {where_sql} {order_sql} LIMIT %(limit)s",
            params,
        )
        return cur.fetchall()


def get_card(conn, card_id: str) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, oracle_text, type_line, mana_cost, artist, image_uris FROM cards WHERE id = %s",
            (card_id,),
        )
        return cur.fetchone()


def search_cards(conn, where_sql: str, params: list, limit: int = 300) -> list[dict]:
    query = f"SELECT {CARD_LIST_COLUMNS} FROM cards WHERE {where_sql} ORDER BY name LIMIT %s"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params + [limit])
        return cur.fetchall()


def nearest_neighbors(conn, embedding: list[float], limit: int = 20, exclude_card_id: str | None = None) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if exclude_card_id:
            cur.execute(
                f"SELECT {CARD_LIST_COLUMNS} FROM cards WHERE embedding IS NOT NULL AND id != %s "
                "ORDER BY embedding <=> %s LIMIT %s",
                (exclude_card_id, embedding, limit),
            )
        else:
            cur.execute(
                f"SELECT {CARD_LIST_COLUMNS} FROM cards WHERE embedding IS NOT NULL "
                "ORDER BY embedding <=> %s LIMIT %s",
                (embedding, limit),
            )
        return cur.fetchall()
