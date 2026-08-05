import os
import tempfile

from backend.pipeline import config as config_module
from backend.pipeline import db, dedupe, storage
from backend.pipeline.caption import AnalysisResult
from backend.pipeline.caption_gemini import build_gemini_analyzer
from backend.pipeline.classify_clip import load_clip_model, passes_content_gate
from backend.pipeline.classify_heuristics import passes_heuristics
from backend.pipeline.embed import build_embedder
from backend.pipeline.persist import persist_image
from backend.pipeline.rate_limit import DailyQuotaExceeded
from backend.pipeline.scrape_deviantart import get_access_token, scrape_deviantart
from backend.pipeline.scrape_reddit import build_reddit_client, scrape_reddit


def _analysis_to_embedding_text(analysis: AnalysisResult) -> str:
    return (
        f"Art piece titled '{analysis.title}'. "
        f"Style: {analysis.art_style}, {analysis.fantasy_mood}, {analysis.fantasy_scale}, {analysis.magic_level}. "
        f"Tags: {', '.join(analysis.tags)}. "
        f"Description: {analysis.caption}"
    )


def run() -> None:
    cfg = config_module.load_config()
    conn = db.get_connection()
    db.init_schema(conn)
    r2_client = storage.get_r2_client()

    with tempfile.TemporaryDirectory() as tmp_dir:
        candidates = []

        try:
            reddit_client = build_reddit_client()
            candidates += scrape_reddit(cfg, reddit_client, tmp_dir)
        except Exception as e:
            print(f"Reddit scrape failed entirely: {e}")

        try:
            token = get_access_token(os.environ["DEVIANTART_CLIENT_ID"], os.environ["DEVIANTART_CLIENT_SECRET"])
            candidates += scrape_deviantart(cfg, token, tmp_dir)
        except Exception as e:
            print(f"DeviantArt scrape failed entirely: {e}")

        candidates = candidates[: cfg.images_per_run]
        new_candidates = dedupe.filter_new(conn, candidates)

        clip_model = load_clip_model()
        analyzer = build_gemini_analyzer(cfg)
        embedder = build_embedder(cfg)

        for candidate, image_hash in new_candidates:
            try:
                if not passes_heuristics(candidate.local_path):
                    continue
                if not passes_content_gate(clip_model, candidate.local_path, cfg.clip_confidence_threshold):
                    continue

                analysis = analyzer.analyze_image(candidate.local_path)
                if not analysis.keep:
                    continue

                embedding = embedder.embed_text(_analysis_to_embedding_text(analysis))
                ext = os.path.splitext(candidate.local_path)[1]
                filename = f"{image_hash}{ext}"
                persist_image(conn, r2_client, candidate.local_path, image_hash, filename, analysis, embedding)
            except DailyQuotaExceeded:
                print("Daily Gemini quota exhausted — stopping run early; already-persisted images are saved.")
                break
            except Exception as e:
                print(f"Skipping {candidate.local_path}: {e}")
                continue

    conn.close()


if __name__ == "__main__":
    run()
