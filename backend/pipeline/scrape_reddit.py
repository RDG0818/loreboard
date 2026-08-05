import os

import praw
import requests

from backend.pipeline.config import PipelineConfig
from backend.pipeline.types import Candidate

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
IMAGE_FORMATS = (".jpg", ".jpeg", ".png", ".webp")
POST_LIMIT = 100


def build_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
    )


def _safe_filename(title: str) -> str:
    return "".join(c for c in title if c.isalpha() or c.isdigit() or c.isspace()).rstrip()[:80]


def _download(url: str, dest_dir: str, base_name: str) -> str | None:
    ext = os.path.splitext(url)[1].split("?")[0]
    if ext not in IMAGE_FORMATS:
        return None
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    dest_path = os.path.join(dest_dir, f"{base_name}{ext}")
    with open(dest_path, "wb") as f:
        f.write(response.content)
    return dest_path


def scrape_reddit(config: PipelineConfig, reddit_client, dest_dir: str) -> list[Candidate]:
    candidates: list[Candidate] = []

    for subreddit_name in config.subreddits:
        try:
            subreddit = reddit_client.subreddit(subreddit_name)
            for submission in subreddit.hot(limit=POST_LIMIT):
                if submission.stickied:
                    continue

                safe_title = _safe_filename(submission.title)
                local_path = _download(submission.url, dest_dir, safe_title)
                if local_path is None:
                    continue

                candidates.append(
                    Candidate(
                        local_path=local_path,
                        source="reddit",
                        source_title=submission.title,
                        source_url=submission.url,
                    )
                )
        except Exception as e:
            print(f"Reddit scrape failed for r/{subreddit_name}: {e}")
            continue

    return candidates
