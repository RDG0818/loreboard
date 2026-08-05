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
