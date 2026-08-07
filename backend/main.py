import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.auth import router as auth_router
from backend.cards_router import router as cards_router
from backend.saves_router import router as saves_router
from backend.views_router import router as views_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET_KEY"])

app.include_router(auth_router)
app.include_router(cards_router)
app.include_router(saves_router)
app.include_router(views_router)
