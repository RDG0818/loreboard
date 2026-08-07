import importlib
import sys

import pytest


def test_missing_frontend_origin_raises_keyerror(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    sys.modules.pop("backend.main", None)

    with pytest.raises(KeyError):
        importlib.import_module("backend.main")


def test_app_exposes_expected_routes(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")
    from backend.main import app

    # FastAPI >=0.141 stores included routers as lazy `_IncludedRouter`
    # wrappers on `app.routes`, so a plain `route.path` walk only sees the
    # four auto-added docs/openapi routes. `app.openapi()["paths"]` forces
    # resolution and reflects the actual mounted routes.
    paths = set(app.openapi()["paths"].keys())

    assert "/api/v1/cards" in paths
    assert "/api/v1/cards/search" in paths
    assert "/api/v1/cards/{card_id}" in paths
    assert "/api/v1/cards/{card_id}/similar" in paths
    assert "/api/v1/recommendations" in paths
    assert "/api/v1/saves" in paths
    assert "/api/v1/saves/{card_id}" in paths
    assert "/api/v1/search/natural" in paths
    assert "/api/v1/views" in paths
    assert "/auth/login/google" in paths
    assert "/auth/callback" in paths
    assert "/api/v1/me" in paths
