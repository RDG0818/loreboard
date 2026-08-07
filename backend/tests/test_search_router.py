from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.search_router import router


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.search_router.get_connection", lambda: MagicMock())
    return TestClient(app)


def test_natural_search_requires_no_auth(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.search_router.resolve_search_query", lambda q: ("cmc <= %s", [3.0]))
    monkeypatch.setattr("backend.search_router.cards.search_cards", lambda conn, sql, params: [{"id": "c1"}])

    response = client.post("/api/v1/search/natural", json={"query": "cheap stuff"})

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_natural_search_passes_query_text_through(monkeypatch):
    client = _client(monkeypatch)
    captured = {}

    def mock_resolve(q):
        captured["q"] = q
        return ("name ILIKE %s", ["%x%"])

    monkeypatch.setattr("backend.search_router.resolve_search_query", mock_resolve)
    monkeypatch.setattr("backend.search_router.cards.search_cards", lambda conn, sql, params: [])

    client.post("/api/v1/search/natural", json={"query": "low cost commanders"})

    assert captured["q"] == "low cost commanders"
