from fastapi import HTTPException, Request

from backend.db import users
from backend.db.connection import get_connection


def get_current_user(request: Request) -> dict | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    conn = get_connection()
    try:
        return users.get_user_by_id(conn, user_id)
    finally:
        conn.close()


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user
