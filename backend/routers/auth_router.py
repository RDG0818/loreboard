import os

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from backend.db import users
from backend.db.connection import get_connection
from backend.services.auth import get_current_user

router = APIRouter()

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/auth/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Google did not return user info")

    conn = get_connection()
    try:
        user = users.get_or_create_user(conn, userinfo["sub"], userinfo["email"])
        conn.commit()
    finally:
        conn.close()

    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/")


@router.get("/api/v1/me")
async def me(request: Request):
    user = get_current_user(request)
    if user is None:
        return {"logged_in": False}
    return {"logged_in": True, "email": user["email"]}
