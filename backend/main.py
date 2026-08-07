import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.auth import router as auth_router
from backend.cards_router import router as cards_router
from backend.recommendations_router import router as recommendations_router
from backend.saves_router import router as saves_router
from backend.search_router import router as search_router
from backend.views_router import router as views_router

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET_KEY"])

app.include_router(auth_router)
app.include_router(cards_router)
app.include_router(recommendations_router)
app.include_router(saves_router)
app.include_router(search_router)
app.include_router(views_router)
