from unittest.mock import MagicMock, patch
from backend.pipeline import db


def test_init_schema_creates_expected_tables():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    db.init_schema(conn)

    executed_sql = cursor.execute.call_args[0][0]
    for table in ("cards", "users", "saves", "views"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in executed_sql
    conn.commit.assert_called_once()


def test_get_connection_creates_extension_before_registering_vector(monkeypatch):
    """On a completely fresh database the `vector` type doesn't exist yet.
    register_vector() looks up that type's OID, so it must not run until
    after CREATE EXTENSION IF NOT EXISTS vector has been executed on this
    connection — otherwise get_connection() itself raises and the pipeline
    can never bootstrap."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    calls = []
    cursor.execute.side_effect = lambda sql: calls.append(("execute", sql))

    with patch("backend.pipeline.db.psycopg2.connect", return_value=conn) as connect_mock, \
         patch("backend.pipeline.db.register_vector", side_effect=lambda c: calls.append(("register_vector", c))) as register_mock:
        result = db.get_connection()

    connect_mock.assert_called_once_with("postgresql://fake")
    cursor.execute.assert_called_once_with(db.CREATE_EXTENSION_SQL)
    register_mock.assert_called_once_with(conn)
    assert result is conn
    # CREATE EXTENSION must run (and commit) before register_vector looks up the type OID
    assert calls == [("execute", db.CREATE_EXTENSION_SQL), ("register_vector", conn)]
