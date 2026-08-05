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
