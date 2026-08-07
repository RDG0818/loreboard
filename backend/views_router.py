from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import require_user
from backend.db import interactions
from backend.db.connection import get_connection

router = APIRouter()


class ViewsRequest(BaseModel):
    card_ids: list[str]


@router.post("/api/v1/views")
def log_views(body: ViewsRequest, user=Depends(require_user)):
    conn = get_connection()
    try:
        interactions.log_views(conn, user["id"], body.card_ids)
        conn.commit()
        return {"logged": len(body.card_ids)}
    finally:
        conn.close()
