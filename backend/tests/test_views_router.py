from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from backend.views_router import router


def test_log_views_requires_auth():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/api/v1/views", json={"card_ids": ["c1"]})
    assert response.status_code == 401


def test_log_views_calls_interactions_log_views(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr("backend.views_router.get_connection", lambda: MagicMock())
    from backend.auth import require_user
    app.dependency_overrides[require_user] = lambda: {"id": 1}
    client = TestClient(app)
    calls = []
    monkeypatch.setattr("backend.views_router.interactions.log_views", lambda conn, uid, cids: calls.append((uid, cids)))

    response = client.post("/api/v1/views", json={"card_ids": ["c1", "c2"]})

    assert response.status_code == 200
    assert calls == [(1, ["c1", "c2"])]
