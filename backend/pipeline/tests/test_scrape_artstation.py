import os
from unittest.mock import MagicMock

import requests

from backend.pipeline.config import PipelineConfig
from backend.pipeline.scrape_artstation import scrape_artstation

NULL_RATE_LIMITER = MagicMock(wait=lambda: None)


def _cfg(**overrides):
    defaults = dict(
        artstation_queries=["fantasy art"],
        deviantart_tags=[],
        images_per_run=10,
        clip_confidence_threshold=0.26,
        gemini_rpm=15,
        gemini_rpd=1200,
    )
    defaults.update(overrides)
    return PipelineConfig(**defaults)


def _search_response(results):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": results}
    return response


def _project(title="Cool Art", hash_id="6Ko1W", cover_ext="jpg"):
    return {
        "title": title,
        "hash_id": hash_id,
        "url": f"https://www.artstation.com/artwork/{hash_id}",
        "smaller_square_cover_url": f"https://cdnb.artstation.com/p/assets/covers/images/012/975/077/smaller_square/art.{cover_ext}?123",
    }


def test_scrape_artstation_downloads_results_per_query(tmp_path):
    search_response = _search_response([_project()])

    image_response = MagicMock()
    image_response.content = b"fake-image-bytes"
    image_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [search_response, image_response]

    candidates = scrape_artstation(_cfg(), str(tmp_path), session=session, rate_limiter=NULL_RATE_LIMITER)

    assert len(candidates) == 1
    assert candidates[0].source == "artstation"
    assert os.path.exists(candidates[0].local_path)


def test_scrape_artstation_downloads_full_res_not_thumbnail(tmp_path):
    """The download must go to the CDN's /original/ path, not the
    /smaller_square/ thumbnail path the search endpoint returns."""
    search_response = _search_response([_project()])

    image_response = MagicMock()
    image_response.content = b"fake-image-bytes"
    image_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [search_response, image_response]

    scrape_artstation(_cfg(), str(tmp_path), session=session, rate_limiter=NULL_RATE_LIMITER)

    download_call = session.get.call_args_list[1]
    downloaded_url = download_call.args[0]
    assert "/original/" in downloaded_url
    assert "/smaller_square/" not in downloaded_url


def test_scrape_artstation_preserves_real_extension(tmp_path):
    search_response = _search_response([_project(cover_ext="png")])

    image_response = MagicMock()
    image_response.content = b"fake-image-bytes"
    image_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [search_response, image_response]

    candidates = scrape_artstation(_cfg(), str(tmp_path), session=session, rate_limiter=NULL_RATE_LIMITER)

    assert len(candidates) == 1
    assert candidates[0].local_path.endswith(".png")


def test_scrape_artstation_skips_project_with_no_cover(tmp_path):
    project = _project()
    del project["smaller_square_cover_url"]
    search_response = _search_response([project])

    session = MagicMock()
    session.get.side_effect = [search_response]

    candidates = scrape_artstation(_cfg(), str(tmp_path), session=session, rate_limiter=NULL_RATE_LIMITER)

    assert candidates == []


def test_scrape_artstation_continues_after_one_query_fails(tmp_path):
    search_response = _search_response([])

    session = MagicMock()
    session.get.side_effect = [RuntimeError("artstation down"), search_response]

    candidates = scrape_artstation(
        _cfg(artstation_queries=["broken", "fantasy art"]), str(tmp_path), session=session, rate_limiter=NULL_RATE_LIMITER
    )

    assert candidates == []
    assert session.get.call_count == 2


def test_scrape_artstation_continues_after_one_image_fails(tmp_path):
    search_response = _search_response(
        [_project(title="Bad Art", hash_id="bad1"), _project(title="Good Art", hash_id="good1")]
    )

    good_image_response = MagicMock()
    good_image_response.content = b"fake-image-bytes"
    good_image_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [search_response, RuntimeError("network timeout"), good_image_response]

    candidates = scrape_artstation(_cfg(), str(tmp_path), session=session, rate_limiter=NULL_RATE_LIMITER)

    assert len(candidates) == 1
    assert candidates[0].source_title == "Good Art"


def test_scrape_artstation_retries_on_429(tmp_path):
    rate_limited_response = MagicMock()
    rate_limited_response.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Too Many Requests")

    search_response = _search_response([])

    session = MagicMock()
    session.get.side_effect = [rate_limited_response, search_response]

    candidates = scrape_artstation(_cfg(), str(tmp_path), session=session, rate_limiter=NULL_RATE_LIMITER)

    assert candidates == []
    assert session.get.call_count == 2


def test_scrape_artstation_paces_requests_with_rate_limiter(tmp_path):
    search_response = _search_response([_project()])

    image_response = MagicMock()
    image_response.content = b"fake-image-bytes"
    image_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [search_response, image_response]

    rate_limiter = MagicMock()
    scrape_artstation(_cfg(), str(tmp_path), session=session, rate_limiter=rate_limiter)

    # One wait() before the search call, one before the image download.
    assert rate_limiter.wait.call_count == 2


def test_scrape_artstation_uses_default_rate_limiter_when_none_given(tmp_path):
    """Sanity check that the function is usable without an explicit
    rate_limiter (production call shape), not just in tests."""
    search_response = _search_response([])
    session = MagicMock()
    session.get.side_effect = [search_response]

    candidates = scrape_artstation(_cfg(), str(tmp_path), session=session)

    assert candidates == []
