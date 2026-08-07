from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.cards_router import router


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.cards_router.get_connection", lambda: MagicMock())
    return TestClient(app)


def test_list_cards_returns_page(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        "backend.cards_router.cards.fetch_cards_page", lambda conn, cursor, limit, seed: [{"id": "c1"}]
    )

    response = client.get("/api/v1/cards")

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_search_cards_returns_400_on_bad_query(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/v1/cards/search", params={"q": "xyz:bad"})

    assert response.status_code == 400


def test_search_cards_returns_results_for_valid_query(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.search_cards", lambda conn, sql, params, **k: [{"id": "c1"}])

    response = client.get("/api/v1/cards/search", params={"q": "cmc<=3"})

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_get_card_returns_404_when_missing(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.get_card", lambda conn, card_id: None)

    response = client.get("/api/v1/cards/nope")

    assert response.status_code == 404


def test_similar_cards_returns_404_when_card_has_no_embedding(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.get_card_embedding", lambda conn, card_id: None)

    response = client.get("/api/v1/cards/c1/similar")

    assert response.status_code == 404


def test_similar_cards_returns_neighbors(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("backend.cards_router.cards.get_card_embedding", lambda conn, card_id: [0.1, 0.2])
    monkeypatch.setattr("backend.cards_router.cards.nearest_neighbors", lambda conn, emb, **k: [{"id": "c2"}])

    response = client.get("/api/v1/cards/c1/similar")

    assert response.status_code == 200
    assert response.json() == [{"id": "c2"}]
