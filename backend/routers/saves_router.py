from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.db import interactions
from backend.db.connection import get_db
from backend.services.auth import require_user

router = APIRouter()


class SaveRequest(BaseModel):
    card_id: str


@router.get("/api/v1/saves")
def list_saves(user=Depends(require_user), conn=Depends(get_db)):
    return interactions.list_saves(conn, user["id"])


@router.post("/api/v1/saves")
def create_save(body: SaveRequest, user=Depends(require_user), conn=Depends(get_db)):
    interactions.add_save(conn, user["id"], body.card_id)
    conn.commit()
    return {"saved": True, "card_id": body.card_id}


@router.delete("/api/v1/saves/{card_id}")
def delete_save(card_id: str, user=Depends(require_user), conn=Depends(get_db)):
    interactions.remove_save(conn, user["id"], card_id)
    conn.commit()
    return {"saved": False, "card_id": card_id}
