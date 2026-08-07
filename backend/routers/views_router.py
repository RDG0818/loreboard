from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.db import interactions
from backend.db.connection import get_db
from backend.services.auth import require_user

router = APIRouter()


class ViewsRequest(BaseModel):
    card_ids: list[str]


@router.post("/api/v1/views")
def log_views(body: ViewsRequest, user=Depends(require_user), conn=Depends(get_db)):
    interactions.log_views(conn, user["id"], body.card_ids)
    conn.commit()
    return {"logged": len(body.card_ids)}
