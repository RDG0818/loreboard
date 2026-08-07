from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from backend.saves_router import router


def _client(monkeypatch, user=None):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.saves_router.get_connection", lambda: MagicMock())
    if user is not None:
        app.dependency_overrides = {}
        from backend.auth import require_user
        app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def test_list_saves_requires_auth():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/v1/saves")
    assert response.status_code == 401


def test_list_saves_returns_saved_cards(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    monkeypatch.setattr("backend.saves_router.interactions.list_saves", lambda conn, uid: [{"id": "c1"}])

    response = client.get("/api/v1/saves")

    assert response.status_code == 200
    assert response.json() == [{"id": "c1"}]


def test_create_save_calls_add_save(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    calls = []
    monkeypatch.setattr("backend.saves_router.interactions.add_save", lambda conn, uid, cid: calls.append((uid, cid)))

    response = client.post("/api/v1/saves", json={"card_id": "c1"})

    assert response.status_code == 200
    assert calls == [(1, "c1")]


def test_delete_save_calls_remove_save(monkeypatch):
    client = _client(monkeypatch, user={"id": 1})
    calls = []
    monkeypatch.setattr("backend.saves_router.interactions.remove_save", lambda conn, uid, cid: calls.append((uid, cid)))

    response = client.delete("/api/v1/saves/c1")

    assert response.status_code == 200
    assert calls == [(1, "c1")]
