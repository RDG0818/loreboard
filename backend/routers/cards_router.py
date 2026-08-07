from fastapi import APIRouter, Depends, HTTPException, Query

from backend.db import cards
from backend.db.connection import get_db
from backend.services.query_parser import QueryParseError, parse_query

router = APIRouter()


@router.get("/api/v1/cards")
def list_cards(
    cursor: str | None = None,
    limit: int = 30,
    seed: str | None = None,
    show_all: bool = False,
    conn=Depends(get_db),
):
    return cards.fetch_cards_page(conn, cursor, limit, seed, include_all=show_all)


@router.get("/api/v1/cards/search")
def search_cards(q: str = Query(...), conn=Depends(get_db)):
    try:
        where_sql, params = parse_query(q)
    except QueryParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return cards.search_cards(conn, where_sql, params)


@router.get("/api/v1/cards/{card_id}")
def get_card(card_id: str, conn=Depends(get_db)):
    card = cards.get_card(conn, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("/api/v1/cards/{card_id}/similar")
def similar_cards(card_id: str, limit: int = 8, conn=Depends(get_db)):
    embedding = cards.get_card_embedding(conn, card_id)
    if embedding is None:
        raise HTTPException(status_code=404, detail="Card not found or has no embedding yet")
    return cards.nearest_neighbors(conn, embedding, limit=limit, exclude_card_id=card_id)
