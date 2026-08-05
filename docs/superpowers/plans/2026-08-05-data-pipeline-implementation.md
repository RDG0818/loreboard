# Data Pipeline Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Loreboard's image-scraping pipeline as a scheduled, GitHub-Actions-driven job that pulls from Reddit and DeviantArt, filters for quality/relevance, captions via Gemini, embeds, and persists to Cloudflare R2 + Supabase Postgres (pgvector) — replacing the lost local dataset and the old local-SQLite/local-disk pipeline.

**Architecture:** A `backend/pipeline/` package of small, independently-testable stage modules (scrape → dedupe → classify → caption → embed → persist), wired together by one orchestrator entrypoint (`run.py`), triggered by a GitHub Actions cron workflow running as a single job.

**Tech Stack:** Python, PRAW (Reddit), `requests` (DeviantArt OAuth client-credentials), `sentence-transformers` (CLIP), `google-generativeai` (Gemini captioning + embeddings), `psycopg2` + `pgvector` (Postgres), `boto3` (R2, S3-compatible), `pytest` + `unittest.mock` for tests.

## Global Constraints

- No ArtStation scraping (spec: excluded entirely).
- No always-on server — GitHub Actions cron is the only scheduler; single job, no multi-job/artifact-passing architecture.
- Storage: images/audio files → Cloudflare R2 (S3-compatible); metadata + vectors → Supabase Postgres with `pgvector`. No local disk persistence beyond a run's temp directory.
- `deviantart_token.txt` must not exist in the repo going forward — DeviantArt auth uses the `client_credentials` OAuth grant (no interactive step, works headlessly in CI).
- Every external-API call (Reddit, DeviantArt, Gemini) must be resilient to that API's rate limits per the spec's table — a limit hit on one API must not abort the run.
- Gemini free tier: ~15 RPM, ~1500 RPD — pipeline must cap daily Gemini usage below 1500 and stop cleanly (not error) on exhaustion, keeping already-persisted images.
- `persist` writes (R2 upload + Postgres row) happen together per image — a failed upload must never result in a committed DB row for that image.
- CLIP is a content-type pre-filter only (per-prompt max similarity, not an averaged prototype) — final quality/relevance judgment is Gemini's `keep`/`rejection_reason` field.
- No integration tests against real external APIs in CI — all external calls are mocked in tests.

---

### Task 1: Pipeline package scaffolding + config

**Files:**
- Create: `backend/pipeline/__init__.py`
- Create: `backend/pipeline/config.py`
- Test: `backend/pipeline/tests/__init__.py`
- Test: `backend/pipeline/tests/test_config.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `PipelineConfig` dataclass (fields: `subreddits: list[str]`, `deviantart_tags: list[str]`, `images_per_run: int`, `clip_confidence_threshold: float`, `gemini_rpm: int`, `gemini_rpd: int`); `load_config() -> PipelineConfig`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_config.py
import os
from backend.pipeline.config import load_config, PipelineConfig


def test_load_config_returns_defaults(monkeypatch):
    monkeypatch.delenv("PIPELINE_IMAGES_PER_RUN", raising=False)
    cfg = load_config()
    assert isinstance(cfg, PipelineConfig)
    assert cfg.images_per_run == 200
    assert "ImaginaryBestOf" in cfg.subreddits
    assert cfg.gemini_rpm == 15
    assert cfg.gemini_rpd == 1200


def test_load_config_honors_images_per_run_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_IMAGES_PER_RUN", "50")
    cfg = load_config()
    assert cfg.images_per_run == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/__init__.py
```

```python
# backend/pipeline/config.py
import dataclasses
import os


@dataclasses.dataclass
class PipelineConfig:
    subreddits: list[str]
    deviantart_tags: list[str]
    images_per_run: int
    clip_confidence_threshold: float
    gemini_rpm: int
    gemini_rpd: int


DEFAULT_CONFIG = PipelineConfig(
    subreddits=[
        "ImaginaryBestOf",
        "ImaginaryLandscapes",
        "ImaginaryWarhammer",
        "ImaginaryMonsters",
        "ImaginaryCharacters",
    ],
    deviantart_tags=["fantasyart", "digitalpainting", "conceptart"],
    images_per_run=200,
    clip_confidence_threshold=0.26,
    gemini_rpm=15,
    gemini_rpd=1200,  # capped comfortably under the 1500/day free-tier limit
)


def load_config() -> PipelineConfig:
    """Loads PipelineConfig from DEFAULT_CONFIG with env var overrides."""
    cfg = DEFAULT_CONFIG
    override = os.getenv("PIPELINE_IMAGES_PER_RUN")
    if override:
        cfg = dataclasses.replace(cfg, images_per_run=int(override))
    return cfg
```

```python
# backend/pipeline/tests/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add new pipeline dependencies to requirements.txt**

Append these lines to `backend/requirements.txt` (keep existing lines unchanged):

```
praw
python-dotenv
google-generativeai
psycopg2-binary
pgvector
boto3
pytest
```

- [ ] **Step 6: Commit**

```bash
git add backend/pipeline/__init__.py backend/pipeline/config.py backend/pipeline/tests/__init__.py backend/pipeline/tests/test_config.py backend/requirements.txt
git commit -m "feat: add pipeline package scaffolding and config"
```

---

### Task 2: Rate limiting & backoff utility

**Files:**
- Create: `backend/pipeline/rate_limit.py`
- Test: `backend/pipeline/tests/test_rate_limit.py`

**Interfaces:**
- Produces: `RateLimiter(calls_per_minute: int, clock=time.monotonic, sleep=time.sleep)` with `.wait() -> None`; `DailyQuota(max_calls_per_day: int)` with `.consume() -> None` raising `DailyQuotaExceeded`; `DailyQuotaExceeded(Exception)`; `with_backoff(func, *, max_retries=5, base_delay=1.0, is_retryable=lambda e: True, sleep=time.sleep) -> T`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_rate_limit.py
import pytest
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded, with_backoff


def test_rate_limiter_sleeps_remaining_interval():
    clock_values = iter([0.0, 0.0, 5.0])  # init call, first wait, second wait
    sleeps = []

    limiter = RateLimiter(
        calls_per_minute=60,  # min_interval = 1.0s
        clock=lambda: next(clock_values),
        sleep=lambda s: sleeps.append(s),
    )
    limiter.wait()  # first call: no prior call, no sleep
    limiter.wait()  # second call: elapsed 5.0s >= 1.0s interval... wait, need not sleep

    assert sleeps == []


def test_rate_limiter_sleeps_when_calls_are_too_close():
    clock_values = iter([0.0, 0.0, 0.2, 0.2])
    sleeps = []

    limiter = RateLimiter(
        calls_per_minute=60,  # min_interval = 1.0s
        clock=lambda: next(clock_values),
        sleep=lambda s: sleeps.append(s),
    )
    limiter.wait()
    limiter.wait()

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.8, abs=0.01)


def test_daily_quota_raises_after_max_calls():
    quota = DailyQuota(max_calls_per_day=2)
    quota.consume()
    quota.consume()
    with pytest.raises(DailyQuotaExceeded):
        quota.consume()


def test_with_backoff_retries_then_succeeds():
    attempts = {"count": 0}
    sleeps = []

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("transient")
        return "ok"

    result = with_backoff(flaky, max_retries=5, base_delay=0.01, sleep=lambda s: sleeps.append(s))

    assert result == "ok"
    assert attempts["count"] == 3
    assert len(sleeps) == 2


def test_with_backoff_raises_after_max_retries():
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        with_backoff(always_fails, max_retries=2, base_delay=0.01, sleep=lambda s: None)


def test_with_backoff_does_not_retry_non_retryable():
    calls = {"count": 0}

    def fails_once():
        calls["count"] += 1
        raise ValueError("non-retryable")

    with pytest.raises(ValueError):
        with_backoff(fails_once, max_retries=5, is_retryable=lambda e: False, sleep=lambda s: None)

    assert calls["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.rate_limit'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/rate_limit.py
import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RateLimiter:
    """Token-bucket-style limiter: blocks the caller until it is safe to
    make another call within `calls_per_minute`."""

    def __init__(
        self,
        calls_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval = 60.0 / calls_per_minute
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_call is not None:
            elapsed = now - self._last_call
            remaining = self.min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_call = self._clock()


class DailyQuotaExceeded(Exception):
    """Raised when a daily call budget has been exhausted."""


class DailyQuota:
    """Tracks calls against a daily budget; raises DailyQuotaExceeded once
    the budget is exhausted."""

    def __init__(self, max_calls_per_day: int):
        self.max_calls_per_day = max_calls_per_day
        self._count = 0

    def consume(self) -> None:
        if self._count >= self.max_calls_per_day:
            raise DailyQuotaExceeded(f"Daily quota of {self.max_calls_per_day} calls exhausted")
        self._count += 1


def with_backoff(
    func: Callable[[], T],
    *,
    max_retries: int = 5,
    base_delay: float = 1.0,
    is_retryable: Callable[[Exception], bool] = lambda e: True,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Calls func with exponential backoff on retryable exceptions."""
    attempt = 0
    while True:
        try:
            return func()
        except Exception as e:
            if not is_retryable(e) or attempt >= max_retries:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            sleep(delay)
            attempt += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_rate_limit.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/rate_limit.py backend/pipeline/tests/test_rate_limit.py
git commit -m "feat: add rate limiter, daily quota, and backoff utility"
```

---

### Task 3: Shared candidate type

**Files:**
- Create: `backend/pipeline/types.py`
- Test: `backend/pipeline/tests/test_types.py`

**Interfaces:**
- Produces: `Candidate` dataclass (fields: `local_path: str`, `source: str`, `source_title: str`, `source_url: str`).

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_types.py
from backend.pipeline.types import Candidate


def test_candidate_holds_expected_fields():
    c = Candidate(
        local_path="/tmp/foo.jpg",
        source="reddit",
        source_title="A cool painting",
        source_url="https://reddit.com/r/x/y",
    )
    assert c.local_path == "/tmp/foo.jpg"
    assert c.source == "reddit"
    assert c.source_title == "A cool painting"
    assert c.source_url == "https://reddit.com/r/x/y"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.types'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/types.py
import dataclasses


@dataclasses.dataclass
class Candidate:
    local_path: str
    source: str  # "reddit" | "deviantart"
    source_title: str
    source_url: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_types.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/types.py backend/pipeline/tests/test_types.py
git commit -m "feat: add shared Candidate type"
```

---

### Task 4: Postgres schema + connection module

**Files:**
- Create: `backend/pipeline/db.py`
- Test: `backend/pipeline/tests/test_db.py`

**Interfaces:**
- Consumes: `with_backoff` (Task 2, for transient-failure retry on network blips — not rate-limit avoidance, Postgres/R2 aren't rate-limit-constrained at this volume).
- Produces: `get_connection()` (returns a `psycopg2` connection with pgvector registered); `init_schema(conn) -> None`; `hash_exists(conn, image_hash: str) -> bool`; `insert_image(conn, record: dict) -> None` (does **not** commit — caller controls the transaction; `record` keys: `hash, filename, title, caption, art_style, fantasy_mood, fantasy_scale, magic_level, tags, dominant_colors, detail_score, mood_score, scale_score, magic_score, embedding, r2_key`).

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_db.py
from unittest.mock import MagicMock
from backend.pipeline import db


def test_hash_exists_true_when_row_found():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)

    assert db.hash_exists(conn, "abc123") is True
    cursor.execute.assert_called_once_with("SELECT 1 FROM images WHERE hash = %s", ("abc123",))


def test_hash_exists_false_when_no_row():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None

    assert db.hash_exists(conn, "abc123") is False


def test_insert_image_executes_without_committing():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    record = {
        "hash": "h1",
        "filename": "f.jpg",
        "title": "T",
        "caption": "C",
        "art_style": "Painterly",
        "fantasy_mood": "Dark Fantasy",
        "fantasy_scale": "Large Scale",
        "magic_level": "High Magic",
        "tags": "Dragon,Castle",
        "dominant_colors": "Crimson Red",
        "detail_score": 8,
        "mood_score": 3,
        "scale_score": 9,
        "magic_score": 9,
        "embedding": [0.1, 0.2, 0.3],
        "r2_key": "images/h1.jpg",
    }

    db.insert_image(conn, record)

    cursor.execute.assert_called_once()
    conn.commit.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.db'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/db.py
import os

import psycopg2
from pgvector.psycopg2 import register_vector

from backend.pipeline.rate_limit import with_backoff

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS images (
    hash TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    caption TEXT NOT NULL,
    art_style TEXT,
    fantasy_mood TEXT,
    fantasy_scale TEXT,
    magic_level TEXT,
    tags TEXT,
    dominant_colors TEXT,
    detail_score INTEGER,
    mood_score INTEGER,
    scale_score INTEGER,
    magic_score INTEGER,
    embedding vector(768),
    r2_key TEXT NOT NULL
);
"""

INSERT_SQL = """
INSERT INTO images (
    hash, filename, title, caption, art_style, fantasy_mood, fantasy_scale,
    magic_level, tags, dominant_colors, detail_score, mood_score,
    scale_score, magic_score, embedding, r2_key
) VALUES (
    %(hash)s, %(filename)s, %(title)s, %(caption)s, %(art_style)s,
    %(fantasy_mood)s, %(fantasy_scale)s, %(magic_level)s, %(tags)s,
    %(dominant_colors)s, %(detail_score)s, %(mood_score)s, %(scale_score)s,
    %(magic_score)s, %(embedding)s, %(r2_key)s
)
"""


def get_connection():
    """Connects to Postgres using DATABASE_URL and registers the pgvector type."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    register_vector(conn)
    return conn


def init_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def hash_exists(conn, image_hash: str) -> bool:
    def _query():
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM images WHERE hash = %s", (image_hash,))
            return cur.fetchone() is not None

    return with_backoff(_query, max_retries=3, base_delay=0.5)


def insert_image(conn, record: dict) -> None:
    """Inserts one image row. Does not commit — caller owns the transaction
    boundary so the R2 upload and the DB write can be coordinated."""

    def _insert():
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, record)

    with_backoff(_insert, max_retries=3, base_delay=0.5)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/db.py backend/pipeline/tests/test_db.py
git commit -m "feat: add Postgres/pgvector schema and connection module"
```

---

### Task 5: R2 storage wrapper

**Files:**
- Create: `backend/pipeline/storage.py`
- Test: `backend/pipeline/tests/test_storage.py`

**Interfaces:**
- Consumes: `with_backoff` (Task 2, for transient-failure retry on network blips).
- Produces: `get_r2_client()`; `upload_image(client, local_path: str, key: str, bucket: str | None = None) -> str` (returns `key`).

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_storage.py
import os
from unittest.mock import MagicMock
from backend.pipeline import storage


def test_upload_image_calls_upload_file_with_expected_args(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()

    key = storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg")

    client.upload_file.assert_called_once_with("/tmp/local.jpg", "loreboard-assets", "images/local.jpg")
    assert key == "images/local.jpg"


def test_upload_image_uses_explicit_bucket_over_env(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()

    storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg", bucket="other-bucket")

    client.upload_file.assert_called_once_with("/tmp/local.jpg", "other-bucket", "images/local.jpg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.storage'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/storage.py
import os

import boto3

from backend.pipeline.rate_limit import with_backoff


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )


def upload_image(client, local_path: str, key: str, bucket: str | None = None) -> str:
    bucket = bucket or os.environ["R2_BUCKET"]
    with_backoff(lambda: client.upload_file(local_path, bucket, key), max_retries=3, base_delay=0.5)
    return key
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_storage.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/storage.py backend/pipeline/tests/test_storage.py
git commit -m "feat: add R2 storage wrapper"
```

---

### Task 6: Reddit scrape stage

**Files:**
- Create: `backend/pipeline/scrape_reddit.py`
- Test: `backend/pipeline/tests/test_scrape_reddit.py`
- Delete: `backend/web_scrapers/reddit_scraper.py` (superseded)

**Interfaces:**
- Consumes: `PipelineConfig` (Task 1), `Candidate` (Task 3).
- Produces: `build_reddit_client()`; `scrape_reddit(config: PipelineConfig, reddit_client, dest_dir: str) -> list[Candidate]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_scrape_reddit.py
import os
from unittest.mock import MagicMock
from backend.pipeline.config import PipelineConfig
from backend.pipeline.scrape_reddit import scrape_reddit


def _make_submission(title, url, stickied=False):
    sub = MagicMock()
    sub.title = title
    sub.url = url
    sub.stickied = stickied
    sub.is_gallery = False
    return sub


def test_scrape_reddit_downloads_direct_images(tmp_path, monkeypatch):
    cfg = PipelineConfig(
        subreddits=["ImaginaryBestOf"],
        deviantart_tags=[],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )

    submission = _make_submission("A Cool Painting", "https://example.com/pic.jpg")
    subreddit = MagicMock()
    subreddit.hot.return_value = [submission]
    reddit_client = MagicMock()
    reddit_client.subreddit.return_value = subreddit

    fake_response = MagicMock()
    fake_response.content = b"fake-image-bytes"
    fake_response.raise_for_status.return_value = None
    monkeypatch.setattr(
        "backend.pipeline.scrape_reddit.requests.get",
        lambda url, headers=None: fake_response,
    )

    candidates = scrape_reddit(cfg, reddit_client, str(tmp_path))

    assert len(candidates) == 1
    assert candidates[0].source == "reddit"
    assert os.path.exists(candidates[0].local_path)
    with open(candidates[0].local_path, "rb") as f:
        assert f.read() == b"fake-image-bytes"


def test_scrape_reddit_skips_stickied_posts(tmp_path, monkeypatch):
    cfg = PipelineConfig(
        subreddits=["ImaginaryBestOf"],
        deviantart_tags=[],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )
    submission = _make_submission("Pinned", "https://example.com/pic.jpg", stickied=True)
    subreddit = MagicMock()
    subreddit.hot.return_value = [submission]
    reddit_client = MagicMock()
    reddit_client.subreddit.return_value = subreddit

    candidates = scrape_reddit(cfg, reddit_client, str(tmp_path))

    assert candidates == []


def test_scrape_reddit_continues_after_one_subreddit_fails(tmp_path, monkeypatch):
    cfg = PipelineConfig(
        subreddits=["Broken", "ImaginaryBestOf"],
        deviantart_tags=[],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )

    submission = _make_submission("A Cool Painting", "https://example.com/pic.jpg")
    good_subreddit = MagicMock()
    good_subreddit.hot.return_value = [submission]

    broken_subreddit = MagicMock()
    broken_subreddit.hot.side_effect = RuntimeError("reddit is down")

    reddit_client = MagicMock()
    reddit_client.subreddit.side_effect = lambda name: (
        broken_subreddit if name == "Broken" else good_subreddit
    )

    fake_response = MagicMock()
    fake_response.content = b"fake-image-bytes"
    fake_response.raise_for_status.return_value = None
    monkeypatch.setattr(
        "backend.pipeline.scrape_reddit.requests.get",
        lambda url, headers=None: fake_response,
    )

    candidates = scrape_reddit(cfg, reddit_client, str(tmp_path))

    assert len(candidates) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_scrape_reddit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.scrape_reddit'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/scrape_reddit.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_scrape_reddit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit and remove the superseded script**

```bash
git rm backend/web_scrapers/reddit_scraper.py
git add backend/pipeline/scrape_reddit.py backend/pipeline/tests/test_scrape_reddit.py
git commit -m "feat: add Reddit scrape stage, remove superseded script"
```

---

### Task 7: DeviantArt scrape stage

**Files:**
- Create: `backend/pipeline/scrape_deviantart.py`
- Test: `backend/pipeline/tests/test_scrape_deviantart.py`
- Delete: `backend/web_scrapers/deviantart_scraper.py` (superseded)
- Delete: `deviantart_token.txt` (obsolete — replaced by non-interactive client-credentials auth)

**Interfaces:**
- Consumes: `PipelineConfig` (Task 1), `Candidate` (Task 3), `with_backoff` (Task 2).
- Produces: `get_access_token(client_id: str, client_secret: str, session=requests) -> str`; `scrape_deviantart(config: PipelineConfig, access_token: str, dest_dir: str, session=requests) -> list[Candidate]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_scrape_deviantart.py
import os
from unittest.mock import MagicMock
from backend.pipeline.config import PipelineConfig
from backend.pipeline.scrape_deviantart import get_access_token, scrape_deviantart


def test_get_access_token_uses_client_credentials_grant():
    fake_response = MagicMock()
    fake_response.json.return_value = {"access_token": "tok-123"}
    fake_response.raise_for_status.return_value = None
    session = MagicMock()
    session.post.return_value = fake_response

    token = get_access_token("cid", "csecret", session=session)

    assert token == "tok-123"
    session.post.assert_called_once_with(
        "https://www.deviantart.com/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": "cid", "client_secret": "csecret"},
    )


def test_scrape_deviantart_downloads_results_per_tag(tmp_path):
    cfg = PipelineConfig(
        subreddits=[],
        deviantart_tags=["fantasyart"],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )

    browse_response = MagicMock()
    browse_response.raise_for_status.return_value = None
    browse_response.json.return_value = {
        "results": [
            {
                "title": "Cool Art",
                "deviationid": "dev1",
                "content": {"src": "https://example.com/art.jpg"},
            }
        ]
    }

    image_response = MagicMock()
    image_response.content = b"fake-image-bytes"
    image_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [browse_response, image_response]

    candidates = scrape_deviantart(cfg, "tok-123", str(tmp_path), session=session)

    assert len(candidates) == 1
    assert candidates[0].source == "deviantart"
    assert os.path.exists(candidates[0].local_path)


def test_scrape_deviantart_continues_after_one_tag_fails(tmp_path):
    cfg = PipelineConfig(
        subreddits=[],
        deviantart_tags=["broken", "fantasyart"],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )

    browse_response = MagicMock()
    browse_response.raise_for_status.return_value = None
    browse_response.json.return_value = {"results": []}

    session = MagicMock()
    session.get.side_effect = [RuntimeError("deviantart down"), browse_response]

    candidates = scrape_deviantart(cfg, "tok-123", str(tmp_path), session=session)

    assert candidates == []
    assert session.get.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_scrape_deviantart.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.scrape_deviantart'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/scrape_deviantart.py
import os

import requests

from backend.pipeline.config import PipelineConfig
from backend.pipeline.rate_limit import with_backoff
from backend.pipeline.types import Candidate

BROWSE_URL = "https://www.deviantart.com/api/v1/oauth2/browse/tags"
TOKEN_URL = "https://www.deviantart.com/oauth2/token"
TAG_LIMIT = 50


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


def scrape_deviantart(
    config: PipelineConfig, access_token: str, dest_dir: str, session=requests
) -> list[Candidate]:
    candidates: list[Candidate] = []
    headers = {"Authorization": f"Bearer {access_token}"}

    for tag in config.deviantart_tags:
        try:
            browse_response = with_backoff(
                lambda: session.get(
                    BROWSE_URL,
                    headers=headers,
                    params={"tag": tag, "limit": TAG_LIMIT, "mature_content": "true"},
                ),
                is_retryable=lambda e: True,
            )
            browse_response.raise_for_status()
            data = browse_response.json()

            for deviation in data.get("results", []):
                image_url = deviation.get("content", {}).get("src")
                if not image_url:
                    continue

                base_name = _safe_filename(deviation["title"], deviation["deviationid"])
                dest_path = os.path.join(dest_dir, f"{base_name}.jpg")

                img_response = with_backoff(lambda: session.get(image_url), is_retryable=lambda e: True)
                img_response.raise_for_status()
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
            print(f"DeviantArt scrape failed for tag '{tag}': {e}")
            continue

    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_scrape_deviantart.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit and remove superseded files**

```bash
git rm backend/web_scrapers/deviantart_scraper.py
git rm --ignore-unmatch deviantart_token.txt
git add backend/pipeline/scrape_deviantart.py backend/pipeline/tests/test_scrape_deviantart.py
git commit -m "feat: add DeviantArt scrape stage using client-credentials auth"
```

---

### Task 8: Dedupe stage

**Files:**
- Create: `backend/pipeline/dedupe.py`
- Test: `backend/pipeline/tests/test_dedupe.py`

**Interfaces:**
- Consumes: `Candidate` (Task 3), `db.hash_exists` (Task 4).
- Produces: `hash_file(path: str) -> str`; `filter_new(conn, candidates: list[Candidate]) -> list[tuple[Candidate, str]]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_dedupe.py
from unittest.mock import MagicMock, patch
from backend.pipeline.types import Candidate
from backend.pipeline import dedupe


def test_hash_file_is_deterministic(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"same-bytes")
    f2 = tmp_path / "b.jpg"
    f2.write_bytes(b"same-bytes")

    assert dedupe.hash_file(str(f)) == dedupe.hash_file(str(f2))


def test_filter_new_excludes_existing_hashes(tmp_path):
    f1 = tmp_path / "new.jpg"
    f1.write_bytes(b"new-content")
    f2 = tmp_path / "old.jpg"
    f2.write_bytes(b"old-content")

    candidates = [
        Candidate(local_path=str(f1), source="reddit", source_title="new", source_url="u1"),
        Candidate(local_path=str(f2), source="reddit", source_title="old", source_url="u2"),
    ]

    old_hash = dedupe.hash_file(str(f2))
    conn = MagicMock()

    with patch("backend.pipeline.dedupe.db.hash_exists", side_effect=lambda c, h: h == old_hash):
        result = dedupe.filter_new(conn, candidates)

    assert len(result) == 1
    assert result[0][0].local_path == str(f1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_dedupe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.dedupe'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/dedupe.py
import hashlib

from backend.pipeline import db
from backend.pipeline.types import Candidate


def hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def filter_new(conn, candidates: list[Candidate]) -> list[tuple[Candidate, str]]:
    """Returns (candidate, hash) pairs for candidates not already present
    in the images table."""
    result = []
    for candidate in candidates:
        image_hash = hash_file(candidate.local_path)
        if not db.hash_exists(conn, image_hash):
            result.append((candidate, image_hash))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_dedupe.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/dedupe.py backend/pipeline/tests/test_dedupe.py
git commit -m "feat: add hash-based dedupe stage"
```

---

### Task 9: Classify — cheap heuristics

**Files:**
- Create: `backend/pipeline/classify_heuristics.py`
- Test: `backend/pipeline/tests/test_classify_heuristics.py`

**Interfaces:**
- Produces: `passes_resolution(path: str, min_width=512, min_height=512) -> bool`; `blur_variance(path: str) -> float`; `passes_blur_check(path: str, threshold=100.0) -> bool`; `passes_heuristics(path: str) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_classify_heuristics.py
import numpy as np
from PIL import Image
from backend.pipeline.classify_heuristics import (
    passes_resolution,
    passes_blur_check,
    passes_heuristics,
)


def _write_image(path, size, arr=None):
    if arr is None:
        img = Image.new("RGB", size, color=(120, 120, 120))
    else:
        img = Image.fromarray(arr, mode="RGB")
    img.save(path)


def test_passes_resolution_rejects_small_image(tmp_path):
    path = tmp_path / "small.jpg"
    _write_image(path, (100, 100))
    assert passes_resolution(str(path)) is False


def test_passes_resolution_accepts_large_image(tmp_path):
    path = tmp_path / "large.jpg"
    _write_image(path, (800, 800))
    assert passes_resolution(str(path)) is True


def test_passes_blur_check_rejects_flat_color(tmp_path):
    path = tmp_path / "flat.jpg"
    _write_image(path, (600, 600))  # solid color: near-zero edge variance
    assert passes_blur_check(str(path)) is False


def test_passes_blur_check_accepts_noisy_image(tmp_path):
    path = tmp_path / "noisy.jpg"
    rng = np.random.default_rng(42)
    arr = rng.integers(0, 255, size=(600, 600, 3), dtype=np.uint8)
    _write_image(path, (600, 600), arr=arr)
    assert passes_blur_check(str(path)) is True


def test_passes_heuristics_requires_both_checks(tmp_path):
    path = tmp_path / "small_flat.jpg"
    _write_image(path, (100, 100))
    assert passes_heuristics(str(path)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_classify_heuristics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.classify_heuristics'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/classify_heuristics.py
import numpy as np
from PIL import Image, ImageFilter

MIN_WIDTH = 512
MIN_HEIGHT = 512
BLUR_VARIANCE_THRESHOLD = 50.0


def passes_resolution(path: str, min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT) -> bool:
    with Image.open(path) as img:
        width, height = img.size
    return width >= min_width and height >= min_height


def blur_variance(path: str) -> float:
    """Higher variance in edge-detected pixels means a sharper image;
    a near-flat image (blurry, or a solid color) has low variance."""
    with Image.open(path) as img:
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        arr = np.asarray(edges, dtype=np.float64)
    return float(arr.var())


def passes_blur_check(path: str, threshold: float = BLUR_VARIANCE_THRESHOLD) -> bool:
    return blur_variance(path) >= threshold


def passes_heuristics(path: str) -> bool:
    return passes_resolution(path) and passes_blur_check(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_classify_heuristics.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/classify_heuristics.py backend/pipeline/tests/test_classify_heuristics.py
git commit -m "feat: add cheap resolution/blur heuristic filters"
```

---

### Task 10: Classify — CLIP content-type gate

**Files:**
- Create: `backend/pipeline/classify_clip.py`
- Test: `backend/pipeline/tests/test_classify_clip.py`
- Delete: `backend/image_sorter/classifier.py` (superseded — averaged-prototype approach replaced)

**Interfaces:**
- Produces: `REJECT_PROMPTS: list[str]`; `load_clip_model(model_name="clip-ViT-L-14")`; `max_reject_similarity(model, image_path: str, reject_prompts=REJECT_PROMPTS) -> float`; `passes_content_gate(model, image_path: str, threshold: float) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_classify_clip.py
from unittest.mock import MagicMock
import numpy as np
from PIL import Image
from backend.pipeline.classify_clip import max_reject_similarity, passes_content_gate


def _make_model(image_vec, prompt_vecs):
    model = MagicMock()

    def encode(x):
        if isinstance(x, list):
            return np.array(prompt_vecs)
        return np.array(image_vec)

    model.encode.side_effect = encode
    return model


def test_max_reject_similarity_returns_highest_single_prompt_score(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10), color=(1, 2, 3)).save(path)

    # image vector is identical to the second reject prompt vector -> similarity 1.0 there
    image_vec = [1.0, 0.0]
    prompt_vecs = [[0.0, 1.0], [1.0, 0.0]]
    model = _make_model(image_vec, prompt_vecs)

    score = max_reject_similarity(model, str(path), reject_prompts=["a", "b"])

    assert score > 0.99


def test_passes_content_gate_rejects_high_similarity(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10), color=(1, 2, 3)).save(path)

    image_vec = [1.0, 0.0]
    prompt_vecs = [[1.0, 0.0]]
    model = _make_model(image_vec, prompt_vecs)

    assert passes_content_gate(model, str(path), threshold=0.26) is False


def test_passes_content_gate_accepts_low_similarity(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10), color=(1, 2, 3)).save(path)

    image_vec = [1.0, 0.0]
    prompt_vecs = [[0.0, 1.0]]
    model = _make_model(image_vec, prompt_vecs)

    assert passes_content_gate(model, str(path), threshold=0.26) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_classify_clip.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.classify_clip'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/classify_clip.py
from PIL import Image
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

REJECT_PROMPTS = [
    "A character reference sheet with multiple views of the same character.",
    "An orthographic character turnaround on a plain white background.",
    "A hand-drawn fantasy map or blueprint diagram.",
    "A black and white pencil sketch or line art drawing without color.",
    "A screenshot of a UI, inventory screen, or item chart.",
    "A photograph of a real person, a meme, or a comic book panel with text bubbles.",
]


def load_clip_model(model_name: str = "clip-ViT-L-14") -> SentenceTransformer:
    return SentenceTransformer(model_name)


def max_reject_similarity(model, image_path: str, reject_prompts: list[str] = REJECT_PROMPTS) -> float:
    """Scores the image against each reject prompt individually (not an
    averaged prototype) and returns the single highest similarity."""
    with Image.open(image_path) as img:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        image_embedding = model.encode(img)
    prompt_embeddings = model.encode(reject_prompts)
    similarities = cos_sim(image_embedding, prompt_embeddings)[0]
    return float(similarities.max())


def passes_content_gate(model, image_path: str, threshold: float) -> bool:
    """Rejects the image if it scores too close to any single reject prompt."""
    return max_reject_similarity(model, image_path) < threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_classify_clip.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit and remove superseded classifier**

```bash
git rm -r backend/image_sorter/classifier.py
git add backend/pipeline/classify_clip.py backend/pipeline/tests/test_classify_clip.py
git commit -m "feat: add CLIP content-type gate, remove averaged-prototype classifier"
```

---

### Task 11: Caption — AnalysisResult + parsing

**Files:**
- Create: `backend/pipeline/caption.py`
- Test: `backend/pipeline/tests/test_caption.py`

**Interfaces:**
- Produces: `AnalysisResult` dataclass (`keep: bool`, `rejection_reason: str | None`, `title: str`, `caption: str`, `art_style: str | None`, `fantasy_mood: str | None`, `fantasy_scale: str | None`, `magic_level: str | None`, `tags: list[str]`, `dominant_colors: list[str]`, `detail_score: int | None`, `mood_score: int | None`, `scale_score: int | None`, `magic_score: int | None`); `MalformedAnalysisError(Exception)`; `parse_analysis_json(raw_json: str) -> AnalysisResult`; `ANALYSIS_PROMPT: str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_caption.py
import json
import pytest
from backend.pipeline.caption import parse_analysis_json, MalformedAnalysisError


def test_parse_analysis_json_valid():
    raw = json.dumps(
        {
            "keep": True,
            "rejection_reason": None,
            "title": "City of Ruins",
            "caption": "A sweeping view of a ruined fantasy city.",
            "analysis": {
                "art_style": "Painterly",
                "fantasy_mood": "Dark Fantasy",
                "fantasy_scale": "Large Scale",
                "magic_level": "High Magic",
                "tags": ["Castle", "Ruins"],
                "dominant_colors": ["Crimson Red", "Ash Gray"],
                "detail_score": 8,
                "mood_score": 2,
                "scale_score": 9,
                "magic_score": 7,
            },
        }
    )

    result = parse_analysis_json(raw)

    assert result.keep is True
    assert result.title == "City of Ruins"
    assert result.tags == ["Castle", "Ruins"]
    assert result.detail_score == 8


def test_parse_analysis_json_rejects_invalid_json():
    with pytest.raises(MalformedAnalysisError):
        parse_analysis_json("not json{{{")


def test_parse_analysis_json_rejects_missing_required_field():
    raw = json.dumps({"title": "No keep field", "caption": "..."})
    with pytest.raises(MalformedAnalysisError):
        parse_analysis_json(raw)


def test_parse_analysis_json_defaults_missing_analysis_fields():
    raw = json.dumps({"keep": False, "title": "T", "caption": "C"})
    result = parse_analysis_json(raw)
    assert result.tags == []
    assert result.dominant_colors == []
    assert result.detail_score is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_caption.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.caption'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/caption.py
import dataclasses
import json

ANALYSIS_PROMPT = """
You are a meticulous visual analyst AI specializing in fantasy art. Analyze
the provided image and return a single, valid JSON object. Do not include
any other text or explanations.

The JSON object must contain these top-level keys:

- "keep": boolean. False if the image is not usable fantasy/digital art —
  e.g. a character reference sheet, a meme, a photo of a real person, a
  blueprint/map, a UI screenshot, or low-quality/unfinished artwork.
- "rejection_reason": if "keep" is false, a short string explaining why;
  otherwise null.
- "title": a short, evocative title (2-6 words).
- "caption": a detailed, vivid paragraph of at least 100 words, grounded in
  visual evidence.
- "analysis": a nested object with:
    - "art_style": one of ["Photorealistic", "Stylized Realism", "Painterly", "Illustration with Line Art", "Anime/Manga Style", "Concept Art Sketch"]
    - "fantasy_mood": one of ["Light Fantasy", "Medium Fantasy", "Dark Fantasy"]
    - "fantasy_scale": one of ["Small Scale", "Medium Scale", "Large Scale"]
    - "magic_level": one of ["Low Magic", "Medium Magic", "High Magic"]
    - "tags": array of relevant tag strings
    - "dominant_colors": array of 3-5 color name strings
    - "detail_score": integer 1-10
    - "mood_score": integer 1-10 (1=dark fantasy, 10=light fantasy)
    - "scale_score": integer 1-10
    - "magic_score": integer 1-10

Your entire output must be ONLY the raw JSON object.
""".strip()


@dataclasses.dataclass
class AnalysisResult:
    keep: bool
    rejection_reason: str | None
    title: str
    caption: str
    art_style: str | None
    fantasy_mood: str | None
    fantasy_scale: str | None
    magic_level: str | None
    tags: list[str]
    dominant_colors: list[str]
    detail_score: int | None
    mood_score: int | None
    scale_score: int | None
    magic_score: int | None


class MalformedAnalysisError(Exception):
    """Raised when the model's response is not valid JSON or is missing
    required fields."""


def parse_analysis_json(raw_json: str) -> AnalysisResult:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise MalformedAnalysisError(f"invalid JSON: {e}") from e

    required = ["keep", "title", "caption"]
    missing = [f for f in required if f not in data]
    if missing:
        raise MalformedAnalysisError(f"missing required fields: {missing}")

    analysis = data.get("analysis", {})
    return AnalysisResult(
        keep=bool(data["keep"]),
        rejection_reason=data.get("rejection_reason"),
        title=data["title"],
        caption=data["caption"],
        art_style=analysis.get("art_style"),
        fantasy_mood=analysis.get("fantasy_mood"),
        fantasy_scale=analysis.get("fantasy_scale"),
        magic_level=analysis.get("magic_level"),
        tags=analysis.get("tags", []),
        dominant_colors=analysis.get("dominant_colors", []),
        detail_score=analysis.get("detail_score"),
        mood_score=analysis.get("mood_score"),
        scale_score=analysis.get("scale_score"),
        magic_score=analysis.get("magic_score"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_caption.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/caption.py backend/pipeline/tests/test_caption.py
git commit -m "feat: add AnalysisResult type and JSON parsing/validation"
```

---

### Task 12: Caption — Gemini analyzer implementation

**Files:**
- Create: `backend/pipeline/caption_gemini.py`
- Test: `backend/pipeline/tests/test_caption_gemini.py`

**Interfaces:**
- Consumes: `AnalysisResult`, `parse_analysis_json`, `MalformedAnalysisError`, `ANALYSIS_PROMPT` (Task 11); `RateLimiter`, `DailyQuota`, `with_backoff` (Task 2); `PipelineConfig` (Task 1).
- Produces: `GeminiAnalyzer(model, rate_limiter: RateLimiter, daily_quota: DailyQuota, max_parse_retries=2)` with `.analyze_image(image_path: str) -> AnalysisResult`; `build_gemini_analyzer(config: PipelineConfig) -> GeminiAnalyzer`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_caption_gemini.py
import json
from unittest.mock import MagicMock
import pytest
from PIL import Image
from backend.pipeline.caption_gemini import GeminiAnalyzer
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded


def _valid_json():
    return json.dumps(
        {
            "keep": True,
            "rejection_reason": None,
            "title": "T",
            "caption": "C",
            "analysis": {
                "art_style": "Painterly",
                "fantasy_mood": "Dark Fantasy",
                "fantasy_scale": "Large Scale",
                "magic_level": "High Magic",
                "tags": ["Dragon"],
                "dominant_colors": ["Crimson Red"],
                "detail_score": 7,
                "mood_score": 3,
                "scale_score": 8,
                "magic_score": 8,
            },
        }
    )


def _no_op_limiter():
    return RateLimiter(calls_per_minute=6000, sleep=lambda s: None)


def test_analyze_image_returns_parsed_result_on_first_try(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(path)

    model = MagicMock()
    model.generate_content.return_value = MagicMock(text=_valid_json())

    analyzer = GeminiAnalyzer(model, _no_op_limiter(), DailyQuota(max_calls_per_day=10))
    result = analyzer.analyze_image(str(path))

    assert result.keep is True
    assert result.title == "T"
    assert model.generate_content.call_count == 1


def test_analyze_image_retries_on_malformed_json_then_succeeds(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(path)

    model = MagicMock()
    model.generate_content.side_effect = [
        MagicMock(text="not json"),
        MagicMock(text=_valid_json()),
    ]

    analyzer = GeminiAnalyzer(model, _no_op_limiter(), DailyQuota(max_calls_per_day=10), max_parse_retries=2)
    result = analyzer.analyze_image(str(path))

    assert result.title == "T"
    assert model.generate_content.call_count == 2


def test_analyze_image_raises_after_exhausting_parse_retries(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(path)

    model = MagicMock()
    model.generate_content.return_value = MagicMock(text="still not json")

    analyzer = GeminiAnalyzer(model, _no_op_limiter(), DailyQuota(max_calls_per_day=10), max_parse_retries=1)

    with pytest.raises(Exception):
        analyzer.analyze_image(str(path))

    assert model.generate_content.call_count == 2


def test_analyze_image_raises_daily_quota_exceeded_without_calling_model(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(path)

    model = MagicMock()
    quota = DailyQuota(max_calls_per_day=0)

    analyzer = GeminiAnalyzer(model, _no_op_limiter(), quota)

    with pytest.raises(DailyQuotaExceeded):
        analyzer.analyze_image(str(path))

    model.generate_content.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_caption_gemini.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.caption_gemini'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/caption_gemini.py
import os

import google.generativeai as genai
from PIL import Image

from backend.pipeline.caption import ANALYSIS_PROMPT, AnalysisResult, MalformedAnalysisError, parse_analysis_json
from backend.pipeline.config import PipelineConfig
from backend.pipeline.rate_limit import DailyQuota, RateLimiter, with_backoff


class GeminiAnalyzer:
    def __init__(
        self,
        model,
        rate_limiter: RateLimiter,
        daily_quota: DailyQuota,
        max_parse_retries: int = 2,
    ):
        self._model = model
        self._rate_limiter = rate_limiter
        self._daily_quota = daily_quota
        self._max_parse_retries = max_parse_retries

    def analyze_image(self, image_path: str) -> AnalysisResult:
        self._daily_quota.consume()  # raises DailyQuotaExceeded before any call is made

        img = Image.open(image_path)
        last_error: Exception | None = None

        for _ in range(self._max_parse_retries + 1):
            self._rate_limiter.wait()
            response = with_backoff(
                lambda: self._model.generate_content(
                    [ANALYSIS_PROMPT, img],
                    generation_config={"response_mime_type": "application/json"},
                )
            )
            try:
                return parse_analysis_json(response.text)
            except MalformedAnalysisError as e:
                last_error = e
                continue

        raise last_error


def build_gemini_analyzer(config: PipelineConfig) -> GeminiAnalyzer:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    rate_limiter = RateLimiter(calls_per_minute=config.gemini_rpm)
    daily_quota = DailyQuota(max_calls_per_day=config.gemini_rpd)
    return GeminiAnalyzer(model, rate_limiter, daily_quota)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_caption_gemini.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/caption_gemini.py backend/pipeline/tests/test_caption_gemini.py
git commit -m "feat: add Gemini captioning analyzer with rate limiting and retry"
```

---

### Task 13: Embed stage

**Files:**
- Create: `backend/pipeline/embed.py`
- Test: `backend/pipeline/tests/test_embed.py`

**Interfaces:**
- Consumes: `RateLimiter`, `DailyQuota`, `with_backoff` (Task 2); `PipelineConfig` (Task 1).
- Produces: `Embedder(embed_fn, rate_limiter: RateLimiter, daily_quota: DailyQuota)` with `.embed_text(text: str) -> list[float]`; `build_embedder(config: PipelineConfig) -> Embedder`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_embed.py
from unittest.mock import MagicMock
import pytest
from backend.pipeline.embed import Embedder
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded


def _no_op_limiter():
    return RateLimiter(calls_per_minute=6000, sleep=lambda s: None)


def test_embed_text_returns_vector_from_embed_fn():
    embed_fn = MagicMock(return_value={"embedding": [0.1, 0.2, 0.3]})
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    result = embedder.embed_text("some text")

    assert result == [0.1, 0.2, 0.3]
    embed_fn.assert_called_once_with(model="models/text-embedding-004", content="some text")


def test_embed_text_raises_daily_quota_exceeded_without_calling_embed_fn():
    embed_fn = MagicMock()
    embedder = Embedder(embed_fn, _no_op_limiter(), DailyQuota(max_calls_per_day=0))

    with pytest.raises(DailyQuotaExceeded):
        embedder.embed_text("some text")

    embed_fn.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_embed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.embed'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/embed.py
import os

import google.generativeai as genai

from backend.pipeline.config import PipelineConfig
from backend.pipeline.rate_limit import DailyQuota, RateLimiter, with_backoff


class Embedder:
    def __init__(self, embed_fn, rate_limiter: RateLimiter, daily_quota: DailyQuota):
        self._embed_fn = embed_fn
        self._rate_limiter = rate_limiter
        self._daily_quota = daily_quota

    def embed_text(self, text: str) -> list[float]:
        self._daily_quota.consume()
        self._rate_limiter.wait()
        result = with_backoff(
            lambda: self._embed_fn(model="models/text-embedding-004", content=text)
        )
        return result["embedding"]


def build_embedder(config: PipelineConfig) -> Embedder:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    rate_limiter = RateLimiter(calls_per_minute=config.gemini_rpm)
    daily_quota = DailyQuota(max_calls_per_day=config.gemini_rpd)
    return Embedder(genai.embed_content, rate_limiter, daily_quota)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_embed.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/embed.py backend/pipeline/tests/test_embed.py
git commit -m "feat: add text embedding stage with rate limiting"
```

---

### Task 14: Persist stage

**Files:**
- Create: `backend/pipeline/persist.py`
- Test: `backend/pipeline/tests/test_persist.py`

**Interfaces:**
- Consumes: `storage.upload_image` (Task 5), `db.insert_image` (Task 4), `AnalysisResult` (Task 11).
- Produces: `persist_image(conn, r2_client, local_path: str, image_hash: str, filename: str, analysis: AnalysisResult, embedding: list[float]) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_persist.py
from unittest.mock import MagicMock, patch
from backend.pipeline.caption import AnalysisResult
from backend.pipeline.persist import persist_image


def _analysis():
    return AnalysisResult(
        keep=True,
        rejection_reason=None,
        title="City of Ruins",
        caption="A caption.",
        art_style="Painterly",
        fantasy_mood="Dark Fantasy",
        fantasy_scale="Large Scale",
        magic_level="High Magic",
        tags=["Castle", "Ruins"],
        dominant_colors=["Crimson Red"],
        detail_score=8,
        mood_score=2,
        scale_score=9,
        magic_score=7,
    )


def test_persist_image_uploads_then_inserts_then_commits():
    conn = MagicMock()
    r2_client = MagicMock()
    calls = []

    with patch("backend.pipeline.persist.storage.upload_image", side_effect=lambda *a, **k: calls.append("upload")) as upload_mock, \
         patch("backend.pipeline.persist.db.insert_image", side_effect=lambda *a, **k: calls.append("insert")) as insert_mock:
        persist_image(conn, r2_client, "/tmp/f.jpg", "hash123", "f.jpg", _analysis(), [0.1, 0.2])

    upload_mock.assert_called_once_with(r2_client, "/tmp/f.jpg", "images/f.jpg")
    insert_mock.assert_called_once()
    conn.commit.assert_called_once()
    assert calls == ["upload", "insert"]  # upload must happen before the DB write


def test_persist_image_does_not_commit_if_upload_fails():
    conn = MagicMock()
    r2_client = MagicMock()

    with patch("backend.pipeline.persist.storage.upload_image", side_effect=RuntimeError("upload failed")):
        try:
            persist_image(conn, r2_client, "/tmp/f.jpg", "hash123", "f.jpg", _analysis(), [0.1, 0.2])
        except RuntimeError:
            pass

    conn.commit.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_persist.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.persist'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/persist.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_persist.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/persist.py backend/pipeline/tests/test_persist.py
git commit -m "feat: add persist stage (R2 upload + Postgres row, single transaction)"
```

---

### Task 15: Orchestrator entrypoint

**Files:**
- Create: `backend/pipeline/run.py`
- Test: `backend/pipeline/tests/test_run.py`

**Interfaces:**
- Consumes: every stage module from Tasks 1-14.
- Produces: `_analysis_to_embedding_text(analysis: AnalysisResult) -> str`; `run() -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/pipeline/tests/test_run.py
from unittest.mock import MagicMock, patch
from backend.pipeline.caption import AnalysisResult
from backend.pipeline.rate_limit import DailyQuotaExceeded
from backend.pipeline.run import _analysis_to_embedding_text, run


def _analysis():
    return AnalysisResult(
        keep=True,
        rejection_reason=None,
        title="City of Ruins",
        caption="A ruined city under a stormy sky.",
        art_style="Painterly",
        fantasy_mood="Dark Fantasy",
        fantasy_scale="Large Scale",
        magic_level="High Magic",
        tags=["Castle", "Ruins"],
        dominant_colors=["Crimson Red"],
        detail_score=8,
        mood_score=2,
        scale_score=9,
        magic_score=7,
    )


def test_analysis_to_embedding_text_includes_key_fields():
    text = _analysis_to_embedding_text(_analysis())
    assert "City of Ruins" in text
    assert "Painterly" in text
    assert "Castle, Ruins" in text
    assert "A ruined city under a stormy sky." in text


def test_run_stops_early_on_daily_quota_but_keeps_already_persisted(tmp_path, monkeypatch):
    from backend.pipeline.types import Candidate

    candidate1 = Candidate(local_path=str(tmp_path / "a.jpg"), source="reddit", source_title="a", source_url="u1")
    candidate2 = Candidate(local_path=str(tmp_path / "b.jpg"), source="reddit", source_title="b", source_url="u2")
    for c in (candidate1, candidate2):
        with open(c.local_path, "wb") as f:
            f.write(b"fake-bytes")

    monkeypatch.setattr("backend.pipeline.run.config_module.load_config", lambda: MagicMock(images_per_run=10))
    monkeypatch.setattr("backend.pipeline.run.db.get_connection", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.db.init_schema", lambda conn: None)
    monkeypatch.setattr("backend.pipeline.run.storage.get_r2_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.build_reddit_client", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.scrape_reddit", lambda cfg, client, dest: [candidate1, candidate2])
    monkeypatch.setattr("backend.pipeline.run.get_access_token", lambda cid, secret: "tok")
    monkeypatch.setattr("backend.pipeline.run.scrape_deviantart", lambda cfg, token, dest: [])
    monkeypatch.setattr("backend.pipeline.run.dedupe.filter_new", lambda conn, cands: [(c, f"hash-{i}") for i, c in enumerate(cands)])
    monkeypatch.setattr("backend.pipeline.run.load_clip_model", lambda: MagicMock())
    monkeypatch.setattr("backend.pipeline.run.passes_heuristics", lambda path: True)
    monkeypatch.setattr("backend.pipeline.run.passes_content_gate", lambda model, path, threshold: True)

    persisted = []
    monkeypatch.setattr("backend.pipeline.run.persist_image", lambda *a, **k: persisted.append(a))

    analyzer = MagicMock()
    analyzer.analyze_image.side_effect = [_analysis(), DailyQuotaExceeded("quota gone")]
    monkeypatch.setattr("backend.pipeline.run.build_gemini_analyzer", lambda cfg: analyzer)

    embedder = MagicMock()
    embedder.embed_text.return_value = [0.1, 0.2]
    monkeypatch.setattr("backend.pipeline.run.build_embedder", lambda cfg: embedder)

    monkeypatch.setenv("DEVIANTART_CLIENT_ID", "cid")
    monkeypatch.setenv("DEVIANTART_CLIENT_SECRET", "csecret")

    run()

    assert len(persisted) == 1  # second image stopped the loop before persisting
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/pipeline/tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.run'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/pipeline/run.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/pipeline/tests/test_run.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/run.py backend/pipeline/tests/test_run.py
git commit -m "feat: add pipeline orchestrator entrypoint"
```

---

### Task 16: GitHub Actions workflow + secret cleanup

**Files:**
- Create: `.github/workflows/data_pipeline.yml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `backend.pipeline.run` (Task 15) as the module invoked by the workflow.
- Produces: a scheduled GitHub Actions workflow.

- [ ] **Step 1: Add `deviantart_token.txt` to `.gitignore`**

Append this line to the end of `/home/ryan/Repos/loreboard/.gitignore` (the file already ends with `backend/audio_dataset` and no trailing newline — add a newline before this addition):

```
deviantart_token.txt
```

- [ ] **Step 2: Write the workflow file**

```yaml
# .github/workflows/data_pipeline.yml
name: Data Pipeline

on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch: {}

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r backend/requirements.txt

      - name: Run pipeline
        env:
          REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}
          REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}
          REDDIT_USER_AGENT: ${{ secrets.REDDIT_USER_AGENT }}
          REDDIT_USERNAME: ${{ secrets.REDDIT_USERNAME }}
          REDDIT_PASSWORD: ${{ secrets.REDDIT_PASSWORD }}
          DEVIANTART_CLIENT_ID: ${{ secrets.DEVIANTART_CLIENT_ID }}
          DEVIANTART_CLIENT_SECRET: ${{ secrets.DEVIANTART_CLIENT_SECRET }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          R2_ENDPOINT_URL: ${{ secrets.R2_ENDPOINT_URL }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
          R2_BUCKET: ${{ secrets.R2_BUCKET }}
        run: python -m backend.pipeline.run
```

- [ ] **Step 3: Validate the workflow YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/data_pipeline.yml')); print('valid')"`
Expected: prints `valid`

- [ ] **Step 4: Run the full pipeline test suite one last time**

Run: `pytest backend/pipeline/ -v`
Expected: PASS (all tests across all pipeline modules)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/data_pipeline.yml .gitignore
git commit -m "feat: add scheduled GitHub Actions workflow for the data pipeline"
```

---

## Post-implementation notes

- The scheduled workflow will fail at runtime until the GitHub Actions repo secrets listed in Task 16 are actually configured (Supabase `DATABASE_URL`, R2 credentials, Reddit/DeviantArt/Gemini keys) — that account/service setup is manual, outside this plan's scope.
- Backend API and frontend changes needed to read from Postgres/R2 instead of SQLite/local disk are a separate sub-project (per the design spec's "Open items").
