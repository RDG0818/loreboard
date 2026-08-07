import asyncio
from unittest.mock import MagicMock
from backend.routers import auth_router


def test_me_returns_logged_in_false_when_no_session(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth_router, "get_current_user", lambda r: None)

    result = asyncio.run(auth_router.me(request))

    assert result == {"logged_in": False}


def test_me_returns_logged_in_true_with_email(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth_router, "get_current_user", lambda r: {"id": 1, "email": "a@b.com"})

    result = asyncio.run(auth_router.me(request))

    assert result == {"logged_in": True, "email": "a@b.com"}
