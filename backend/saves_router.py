from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import require_user
from backend.pipeline import interactions
from backend.pipeline.db import get_connection

router = APIRouter()


class SaveRequest(BaseModel):
    card_id: str


@router.get("/api/v1/saves")
def list_saves(user=Depends(require_user)):
    conn = get_connection()
    try:
        return interactions.list_saves(conn, user["id"])
    finally:
        conn.close()


@router.post("/api/v1/saves")
def create_save(body: SaveRequest, user=Depends(require_user)):
    conn = get_connection()
    try:
        interactions.add_save(conn, user["id"], body.card_id)
        conn.commit()
        return {"saved": True, "card_id": body.card_id}
    finally:
        conn.close()


@router.delete("/api/v1/saves/{card_id}")
def delete_save(card_id: str, user=Depends(require_user)):
    conn = get_connection()
    try:
        interactions.remove_save(conn, user["id"], card_id)
        conn.commit()
        return {"saved": False, "card_id": card_id}
    finally:
        conn.close()
