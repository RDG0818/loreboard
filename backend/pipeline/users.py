import psycopg2.extras


def get_or_create_user(conn, google_sub: str, email: str) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, google_sub, email FROM users WHERE google_sub = %s", (google_sub,))
        row = cur.fetchone()
        if row:
            return row
        cur.execute(
            "INSERT INTO users (google_sub, email) VALUES (%s, %s) RETURNING id, google_sub, email",
            (google_sub, email),
        )
        return cur.fetchone()


def get_user_by_id(conn, user_id: int) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, google_sub, email FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()
