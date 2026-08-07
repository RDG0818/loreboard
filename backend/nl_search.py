import os

from google import genai

from backend.query_parser import QueryParseError, parse_query

GENERATION_MODEL = "gemini-flash-latest"

TRANSLATION_PROMPT = """Translate this Magic: The Gathering card search request into a compact query using ONLY this grammar, space-separated, one condition per token:

cmc<=N / cmc>=N / cmc<N / cmc>N / cmc=N   (mana value)
t:WORD       (card type contains WORD — single word only, no quotes or spaces)
o:WORD       (oracle text contains WORD — single word only, no quotes or spaces)
c:WUBRG      (colors, any combination of the letters W U B R G)
id:WUBRG     (color identity, e.g. for Commander)
f:FORMAT     (legal in FORMAT, e.g. f:commander, f:standard)
WORD         (bare word matches the card name)

Reply with ONLY the query, no explanation, no punctuation around it.

Example:
Request: "cheap legendary creatures that draw cards"
Reply: cmc<=3 t:legendary t:creature o:draw

Request: "{request}"
Reply:"""


class _GenerateContentAdapter:
    """Wraps a google-genai Client to expose the old
    `model.generate_content(prompt) -> response` shape, so callers (and
    tests, which inject a plain mock in that shape) don't need to know
    about the new SDK's client.models.generate_content(model=, contents=)
    call convention."""

    def __init__(self, client: genai.Client, model_name: str):
        self._client = client
        self._model_name = model_name

    def generate_content(self, prompt: str):
        return self._client.models.generate_content(model=self._model_name, contents=prompt)


# In-process cache: NL text -> translated grammar string. Translation is a
# pure-ish function of the input text (same phrasing -> same output), so
# repeat searches (retyping, or different users hitting a popular phrase)
# skip the Gemini round-trip entirely. Keyed on normalized (trimmed,
# lowercased) text — exact repeats only, paraphrases still miss. In-process
# dict means it resets on restart and isn't shared across multiple backend
# instances; see TRICKS.md for the upgrade path if that starts to matter.
_translation_cache: dict[str, str] = {}


def translate_natural_language_query(text: str, model=None) -> str:
    cache_key = text.strip().lower()
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    if model is None:
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        model = _GenerateContentAdapter(client, GENERATION_MODEL)
    response = model.generate_content(TRANSLATION_PROMPT.format(request=text))
    translated = response.text.strip()
    _translation_cache[cache_key] = translated
    return translated


def resolve_search_query(text: str, model=None) -> tuple[str, list]:
    """Translates natural language into the structured query grammar and
    parses it. Falls back to a plain name/oracle-text search on the raw
    input if the LLM call fails or its output doesn't parse — NL search
    should degrade to a basic search, never a hard error."""
    try:
        translated = translate_natural_language_query(text, model=model)
        return parse_query(translated)
    except Exception:
        return "(name ILIKE %s OR oracle_text ILIKE %s)", [f"%{text}%", f"%{text}%"]
