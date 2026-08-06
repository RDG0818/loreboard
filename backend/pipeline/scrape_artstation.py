import os

import requests

from backend.pipeline.config import PipelineConfig
from backend.pipeline.rate_limit import RateLimiter, with_backoff
from backend.pipeline.types import Candidate

SEARCH_URL = "https://www.artstation.com/api/v2/search/projects.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
RESULTS_PER_QUERY = 50
DEFAULT_CALLS_PER_MINUTE = 60
IMAGE_FORMATS = (".jpg", ".jpeg", ".png", ".webp")
DEFAULT_EXTENSION = ".jpg"


def _safe_filename(title: str, hash_id: str) -> str:
    safe_title = "".join(c for c in title if c.isalpha() or c.isdigit() or c.isspace()).rstrip()[:50]
    return f"{safe_title}_{hash_id}"


def _full_res_url(cover_url: str) -> str:
    """The search endpoint only returns a cropped thumbnail. The per-project
    detail endpoint that would normally list full-res assets is
    Cloudflare-protected and 403s unauthenticated scripted requests, but the
    CDN serves the original file by swapping the size segment in the same
    thumbnail path."""
    return cover_url.replace("/smaller_square/", "/original/")


def _extension_from_url(url: str) -> str:
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    return ext if ext in IMAGE_FORMATS else DEFAULT_EXTENSION


def _is_transient(e: Exception) -> bool:
    """Returns True only for transient errors that may succeed on retry."""
    return isinstance(e, requests.exceptions.RequestException)


def _get(session, url, **kwargs):
    """Helper that fetches and raises on HTTP error status inside the retried closure."""
    response = session.get(url, **kwargs)
    response.raise_for_status()
    return response


def scrape_artstation(
    config: PipelineConfig,
    dest_dir: str,
    session=requests,
    rate_limiter: RateLimiter | None = None,
) -> list[Candidate]:
    if rate_limiter is None:
        rate_limiter = RateLimiter(calls_per_minute=DEFAULT_CALLS_PER_MINUTE)

    candidates: list[Candidate] = []

    for query in config.artstation_queries:
        try:
            rate_limiter.wait()
            search_response = with_backoff(
                lambda: _get(
                    session,
                    SEARCH_URL,
                    headers=HEADERS,
                    params={"query": query, "page": 1, "per_page": RESULTS_PER_QUERY},
                ),
                is_retryable=_is_transient,
            )
            data = search_response.json()

            for project in data.get("data", []):
                try:
                    cover_url = project.get("smaller_square_cover_url")
                    if not cover_url:
                        continue

                    image_url = _full_res_url(cover_url)
                    base_name = _safe_filename(project["title"], project["hash_id"])
                    dest_path = os.path.join(dest_dir, f"{base_name}{_extension_from_url(image_url)}")

                    rate_limiter.wait()
                    img_response = with_backoff(
                        lambda: _get(session, image_url, headers=HEADERS), is_retryable=_is_transient
                    )
                    with open(dest_path, "wb") as f:
                        f.write(img_response.content)

                    candidates.append(
                        Candidate(
                            local_path=dest_path,
                            source="artstation",
                            source_title=project["title"],
                            source_url=project.get("url", image_url),
                        )
                    )
                except Exception as e:
                    print(f"ArtStation scrape: skipping project in query '{query}': {e}")
                    continue
        except Exception as e:
            print(f"ArtStation scrape failed for query '{query}': {e}")
            continue

    return candidates
