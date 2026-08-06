import psycopg2.extras


def add_save(conn, user_id: int, card_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO saves (user_id, card_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user_id, card_id),
        )


def remove_save(conn, user_id: int, card_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM saves WHERE user_id = %s AND card_id = %s", (user_id, card_id))


def list_saves(conn, user_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT c.id, c.name, c.artist, c.image_uris FROM saves s "
            "JOIN cards c ON c.id = s.card_id WHERE s.user_id = %s ORDER BY s.saved_at DESC",
            (user_id,),
        )
        return cur.fetchall()


def list_saved_card_embeddings(conn, user_id: int) -> list[list[float]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.embedding FROM saves s JOIN cards c ON c.id = s.card_id "
            "WHERE s.user_id = %s AND c.embedding IS NOT NULL",
            (user_id,),
        )
        return [row[0] for row in cur.fetchall()]


def log_views(conn, user_id: int, card_ids: list[str]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO views (user_id, card_id) VALUES (%s, %s)",
            [(user_id, cid) for cid in card_ids],
        )
