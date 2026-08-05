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


def test_scrape_deviantart_continues_after_one_image_fails(tmp_path):
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
            {"title": "Bad Art", "deviationid": "dev1", "content": {"src": "https://example.com/bad.jpg"}},
            {"title": "Good Art", "deviationid": "dev2", "content": {"src": "https://example.com/good.jpg"}},
        ]
    }

    good_image_response = MagicMock()
    good_image_response.content = b"fake-image-bytes"
    good_image_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [browse_response, RuntimeError("network timeout"), good_image_response]

    candidates = scrape_deviantart(cfg, "tok-123", str(tmp_path), session=session)

    assert len(candidates) == 1
    assert candidates[0].source_title == "Good Art"
