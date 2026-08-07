from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from backend.recommendations_router import router


def _client(monkeypatch, user):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.recommendations_router.get_connection", lambda: MagicMock())
    from backend.auth import require_user
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def test_recommendations_requires_auth():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/v1/recommendations")
    assert response.status_code == 401


def test_recommendations_returns_friendly_message_with_zero_saves(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    monkeypatch.setattr("backend.recommendations_router.interactions.list_saved_card_embeddings", lambda conn, uid: [])

    response = client.get("/api/v1/recommendations")

    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"] == []
    assert "message" in body


def test_recommendations_returns_nearest_neighbors_of_taste_vector(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    monkeypatch.setattr(
        "backend.recommendations_router.interactions.list_saved_card_embeddings",
        lambda conn, uid: [[1.0, 2.0], [3.0, 4.0]],
    )
    captured = {}

    def fake_nearest_neighbors(conn, embedding, **kwargs):
        captured["embedding"] = embedding
        return [{"id": "c1"}]

    monkeypatch.setattr("backend.recommendations_router.cards.nearest_neighbors", fake_nearest_neighbors)

    response = client.get("/api/v1/recommendations")

    assert response.status_code == 200
    assert response.json() == {"recommendations": [{"id": "c1"}]}
    assert captured["embedding"] == [2.0, 3.0]
