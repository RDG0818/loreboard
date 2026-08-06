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
from backend.pipeline.rate_limit import DailyQuota, DailyQuotaExceeded, RateLimiter
from backend.pipeline.scrape_artstation import scrape_artstation
from backend.pipeline.scrape_deviantart import get_access_token, scrape_deviantart


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
    try:
        db.init_schema(conn)
        r2_client = storage.get_r2_client()

        with tempfile.TemporaryDirectory() as tmp_dir:
            artstation_candidates: list = []
            deviantart_candidates: list = []

            try:
                artstation_candidates = scrape_artstation(cfg, tmp_dir)
            except Exception as e:
                print(f"ArtStation scrape failed entirely: {e}")

            try:
                token = get_access_token(os.environ["DEVIANTART_CLIENT_ID"], os.environ["DEVIANTART_CLIENT_SECRET"])
                deviantart_candidates = scrape_deviantart(cfg, token, tmp_dir)
            except Exception as e:
                print(f"DeviantArt scrape failed entirely: {e}")

            # Cap each source independently before combining so a single
            # over-productive source can't crowd the other one out entirely
            # once the combined list is truncated.
            per_source_cap = cfg.images_per_run // 2
            candidates = artstation_candidates[:per_source_cap] + deviantart_candidates[:per_source_cap]
            new_candidates = dedupe.filter_new(conn, candidates)

            clip_model = load_clip_model()
            # A single shared RateLimiter/DailyQuota, since the design budget
            # (gemini_rpm/gemini_rpd) is one ceiling covering both caption
            # and embed calls to the Gemini API — not a separate budget each.
            gemini_rate_limiter = RateLimiter(calls_per_minute=cfg.gemini_rpm)
            gemini_daily_quota = DailyQuota(max_calls_per_day=cfg.gemini_rpd)
            analyzer = build_gemini_analyzer(cfg, gemini_rate_limiter, gemini_daily_quota)
            embedder = build_embedder(cfg, gemini_rate_limiter, gemini_daily_quota)

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
    finally:
        conn.close()


if __name__ == "__main__":
    run()
