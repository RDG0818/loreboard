import os
from unittest.mock import MagicMock
from backend.pipeline.config import PipelineConfig
from backend.pipeline.scrape_reddit import scrape_reddit


def _make_submission(title, url, stickied=False, submission_id="abc123"):
    sub = MagicMock()
    sub.id = submission_id
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


def test_scrape_reddit_continues_after_one_image_fails(tmp_path, monkeypatch):
    cfg = PipelineConfig(
        subreddits=["ImaginaryBestOf"],
        deviantart_tags=[],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )

    # Two submissions in same subreddit
    bad_submission = _make_submission("Bad Image", "https://example.com/bad.jpg")
    good_submission = _make_submission("Good Image", "https://example.com/good.jpg")

    subreddit = MagicMock()
    subreddit.hot.return_value = [bad_submission, good_submission]
    reddit_client = MagicMock()
    reddit_client.subreddit.return_value = subreddit

    # Mock requests.get to fail for the first URL and succeed for the second
    def mock_get(url, headers=None):
        if "bad" in url:
            raise RuntimeError("Network timeout downloading image")
        else:
            fake_response = MagicMock()
            fake_response.content = b"good-image-bytes"
            fake_response.raise_for_status.return_value = None
            return fake_response

    monkeypatch.setattr(
        "backend.pipeline.scrape_reddit.requests.get",
        mock_get,
    )

    candidates = scrape_reddit(cfg, reddit_client, str(tmp_path))

    # Should have one candidate from the good submission, bad one skipped
    assert len(candidates) == 1
    assert candidates[0].source_title == "Good Image"
    assert os.path.exists(candidates[0].local_path)
    with open(candidates[0].local_path, "rb") as f:
        assert f.read() == b"good-image-bytes"


def test_scrape_reddit_same_titled_submissions_get_distinct_filenames(tmp_path, monkeypatch):
    """Two submissions with the same (or same-after-truncation) title must not
    overwrite each other's downloaded file — the submission id disambiguates
    the filename."""
    cfg = PipelineConfig(
        subreddits=["ImaginaryBestOf"],
        deviantart_tags=[],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )

    submission1 = _make_submission("Same Title", "https://example.com/one.jpg", submission_id="id1")
    submission2 = _make_submission("Same Title", "https://example.com/two.jpg", submission_id="id2")
    subreddit = MagicMock()
    subreddit.hot.return_value = [submission1, submission2]
    reddit_client = MagicMock()
    reddit_client.subreddit.return_value = subreddit

    def mock_get(url, headers=None):
        fake_response = MagicMock()
        fake_response.content = b"bytes-for-" + url.encode()
        fake_response.raise_for_status.return_value = None
        return fake_response

    monkeypatch.setattr("backend.pipeline.scrape_reddit.requests.get", mock_get)

    candidates = scrape_reddit(cfg, reddit_client, str(tmp_path))

    assert len(candidates) == 2
    paths = {c.local_path for c in candidates}
    assert len(paths) == 2  # distinct filenames — neither download overwrote the other
    assert "id1" in candidates[0].local_path
    assert "id2" in candidates[1].local_path
    with open(candidates[0].local_path, "rb") as f:
        assert f.read() == b"bytes-for-https://example.com/one.jpg"
    with open(candidates[1].local_path, "rb") as f:
        assert f.read() == b"bytes-for-https://example.com/two.jpg"
