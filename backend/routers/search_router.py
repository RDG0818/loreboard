from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.db import cards
from backend.db.connection import get_db
from backend.services.nl_search import resolve_search_query

router = APIRouter()


class NaturalSearchRequest(BaseModel):
    query: str


@router.post("/api/v1/search/natural")
def natural_search(body: NaturalSearchRequest, conn=Depends(get_db)):
    where_sql, params = resolve_search_query(body.query)
    return cards.search_cards(conn, where_sql, params)
