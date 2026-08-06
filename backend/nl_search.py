import os

import google.generativeai as genai

from backend.query_parser import QueryParseError, parse_query

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


def translate_natural_language_query(text: str, model=None) -> str:
    if model is None:
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
    response = model.generate_content(TRANSLATION_PROMPT.format(request=text))
    return response.text.strip()


def resolve_search_query(text: str, model=None) -> tuple[str, list]:
    """Translates natural language into the structured query grammar and
    parses it. Falls back to a plain name/oracle-text search on the raw
    input if the LLM call fails or its output doesn't parse — NL search
    should degrade to a basic search, never a hard error."""
    try:
        translated = translate_natural_language_query(text, model=model)
        tokens = translated.strip().split()

        # If translation contains multiple bare tokens with no special syntax,
        # it's probably gibberish from the LLM — treat as invalid
        has_special_syntax = any(":" in token or token.startswith("cmc") for token in tokens)
        if len(tokens) > 1 and not has_special_syntax:
            raise QueryParseError("Invalid translation: multiple bare tokens with no special syntax")

        return parse_query(translated)
    except Exception:
        return "(name ILIKE %s OR oracle_text ILIKE %s)", [f"%{text}%", f"%{text}%"]
