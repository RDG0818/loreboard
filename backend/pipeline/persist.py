from backend.pipeline import db, storage
from backend.pipeline.caption import AnalysisResult


def persist_image(
    conn,
    r2_client,
    local_path: str,
    image_hash: str,
    filename: str,
    analysis: AnalysisResult,
    embedding: list[float],
) -> None:
    """Uploads the image to R2, then writes its row to Postgres and commits.
    If the upload raises, no DB row is written — the caller can safely
    retry this image on the next run without leaving orphaned state."""
    r2_key = f"images/{filename}"
    storage.upload_image(r2_client, local_path, r2_key)

    record = {
        "hash": image_hash,
        "filename": filename,
        "title": analysis.title,
        "caption": analysis.caption,
        "art_style": analysis.art_style,
        "fantasy_mood": analysis.fantasy_mood,
        "fantasy_scale": analysis.fantasy_scale,
        "magic_level": analysis.magic_level,
        "tags": ",".join(analysis.tags),
        "dominant_colors": ",".join(analysis.dominant_colors),
        "detail_score": analysis.detail_score,
        "mood_score": analysis.mood_score,
        "scale_score": analysis.scale_score,
        "magic_score": analysis.magic_score,
        "embedding": embedding,
        "r2_key": r2_key,
    }
    db.insert_image(conn, record)
    conn.commit()
