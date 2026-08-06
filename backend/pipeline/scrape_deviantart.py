import os

import requests

from backend.pipeline.config import PipelineConfig
from backend.pipeline.rate_limit import with_backoff
from backend.pipeline.types import Candidate

BROWSE_URL = "https://www.deviantart.com/api/v1/oauth2/browse/tags"
TOKEN_URL = "https://www.deviantart.com/oauth2/token"
TAG_LIMIT = 50
IMAGE_FORMATS = (".jpg", ".jpeg", ".png", ".webp")
DEFAULT_EXTENSION = ".jpg"


def get_access_token(client_id: str, client_secret: str, session=requests) -> str:
    """Fetches a client-credentials (application-only) access token — no
    interactive browser step, safe to run headlessly in CI."""
    response = session.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _safe_filename(title: str, deviation_id: str) -> str:
    safe_title = "".join(c for c in title if c.isalpha() or c.isdigit() or c.isspace()).rstrip()[:50]
    return f"{safe_title}_{deviation_id}"


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


def scrape_deviantart(
    config: PipelineConfig, access_token: str, dest_dir: str, session=requests
) -> list[Candidate]:
    candidates: list[Candidate] = []
    headers = {"Authorization": f"Bearer {access_token}"}

    for tag in config.deviantart_tags:
        try:
            browse_response = with_backoff(
                lambda: _get(
                    session,
                    BROWSE_URL,
                    headers=headers,
                    params={"tag": tag, "limit": TAG_LIMIT, "mature_content": "true"},
                ),
                is_retryable=_is_transient,
            )
            data = browse_response.json()

            for deviation in data.get("results", []):
                try:
                    image_url = deviation.get("content", {}).get("src")
                    if not image_url:
                        continue

                    base_name = _safe_filename(deviation["title"], deviation["deviationid"])
                    dest_path = os.path.join(dest_dir, f"{base_name}{_extension_from_url(image_url)}")

                    img_response = with_backoff(lambda: _get(session, image_url), is_retryable=_is_transient)
                    with open(dest_path, "wb") as f:
                        f.write(img_response.content)

                    candidates.append(
                        Candidate(
                            local_path=dest_path,
                            source="deviantart",
                            source_title=deviation["title"],
                            source_url=image_url,
                        )
                    )
                except Exception as e:
                    print(f"DeviantArt scrape: skipping deviation in tag '{tag}': {e}")
                    continue
        except Exception as e:
            print(f"DeviantArt scrape failed for tag '{tag}': {e}")
            continue

    return candidates
