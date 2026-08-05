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
