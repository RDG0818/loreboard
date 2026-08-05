import json
from unittest.mock import MagicMock
import pytest
from PIL import Image
from google.api_core import exceptions as google_exceptions
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


def test_analyze_image_retries_on_transient_error_then_succeeds(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(path)

    model = MagicMock()
    model.generate_content.side_effect = [
        google_exceptions.ServiceUnavailable("Service unavailable"),
        MagicMock(text=_valid_json()),
    ]

    analyzer = GeminiAnalyzer(model, _no_op_limiter(), DailyQuota(max_calls_per_day=10))
    result = analyzer.analyze_image(str(path))

    assert result.keep is True
    assert result.title == "T"
    assert model.generate_content.call_count == 2


def test_analyze_image_propagates_non_transient_error_immediately(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(path)

    model = MagicMock()
    model.generate_content.side_effect = google_exceptions.InvalidArgument("Invalid argument")

    analyzer = GeminiAnalyzer(model, _no_op_limiter(), DailyQuota(max_calls_per_day=10))

    with pytest.raises(google_exceptions.InvalidArgument):
        analyzer.analyze_image(str(path))

    assert model.generate_content.call_count == 1
