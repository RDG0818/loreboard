from fastapi import APIRouter
from pydantic import BaseModel

from backend.nl_search import resolve_search_query
from backend.pipeline import cards
from backend.pipeline.db import get_connection

router = APIRouter()


class NaturalSearchRequest(BaseModel):
    query: str


@router.post("/api/v1/search/natural")
def natural_search(body: NaturalSearchRequest):
    where_sql, params = resolve_search_query(body.query)
    conn = get_connection()
    try:
        return cards.search_cards(conn, where_sql, params)
    finally:
        conn.close()
