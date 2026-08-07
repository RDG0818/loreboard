from fastapi import APIRouter, HTTPException, Query

from backend.pipeline import cards
from backend.pipeline.db import get_connection
from backend.query_parser import QueryParseError, parse_query

router = APIRouter()


@router.get("/api/v1/cards")
def list_cards(cursor: str | None = None, limit: int = 30, seed: str | None = None):
    conn = get_connection()
    try:
        return cards.fetch_cards_page(conn, cursor, limit, seed)
    finally:
        conn.close()


@router.get("/api/v1/cards/search")
def search_cards(q: str = Query(...)):
    try:
        where_sql, params = parse_query(q)
    except QueryParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conn = get_connection()
    try:
        return cards.search_cards(conn, where_sql, params)
    finally:
        conn.close()


@router.get("/api/v1/cards/{card_id}")
def get_card(card_id: str):
    conn = get_connection()
    try:
        card = cards.get_card(conn, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Card not found")
        return card
    finally:
        conn.close()


@router.get("/api/v1/cards/{card_id}/similar")
def similar_cards(card_id: str, limit: int = 8):
    conn = get_connection()
    try:
        embedding = cards.get_card_embedding(conn, card_id)
        if embedding is None:
            raise HTTPException(status_code=404, detail="Card not found or has no embedding yet")
        return cards.nearest_neighbors(conn, embedding, limit=limit, exclude_card_id=card_id)
    finally:
        conn.close()
