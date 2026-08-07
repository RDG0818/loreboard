import asyncio
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException
from backend import auth


def test_get_current_user_returns_none_without_session():
    request = MagicMock()
    request.session = {}
    assert auth.get_current_user(request) is None


def test_get_current_user_looks_up_user_from_session(monkeypatch):
    request = MagicMock()
    request.session = {"user_id": 5}
    conn = MagicMock()
    monkeypatch.setattr(auth, "get_connection", lambda: conn)
    monkeypatch.setattr(auth.users, "get_user_by_id", lambda conn, uid: {"id": 5, "email": "a@b.com"})

    result = auth.get_current_user(request)

    assert result == {"id": 5, "email": "a@b.com"}
    conn.close.assert_called_once()


def test_require_user_raises_401_when_not_logged_in(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: None)

    with pytest.raises(HTTPException) as exc_info:
        auth.require_user(request)
    assert exc_info.value.status_code == 401


def test_require_user_returns_user_when_logged_in(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: {"id": 1})
    assert auth.require_user(request) == {"id": 1}


def test_me_returns_logged_in_false_when_no_session(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: None)

    result = asyncio.run(auth.me(request))

    assert result == {"logged_in": False}


def test_me_returns_logged_in_true_with_email(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: {"id": 1, "email": "a@b.com"})

    result = asyncio.run(auth.me(request))

    assert result == {"logged_in": True, "email": "a@b.com"}
