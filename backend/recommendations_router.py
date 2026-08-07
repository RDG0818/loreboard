from fastapi import APIRouter, Depends

from backend.auth import require_user
from backend.pipeline import cards, interactions
from backend.pipeline.db import get_connection
from backend.recommendations import compute_taste_vector

router = APIRouter()


@router.get("/api/v1/recommendations")
def get_recommendations(user=Depends(require_user)):
    conn = get_connection()
    try:
        embeddings = interactions.list_saved_card_embeddings(conn, user["id"])
        taste_vector = compute_taste_vector(embeddings)
        if taste_vector is None:
            return {"recommendations": [], "message": "Save some cards to get recommendations."}
        return {"recommendations": cards.nearest_neighbors(conn, taste_vector, limit=20)}
    finally:
        conn.close()
