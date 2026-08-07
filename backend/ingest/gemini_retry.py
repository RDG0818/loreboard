from google.genai import errors as genai_errors

_TRANSIENT_STATUS_CODES = {429, 500, 503, 504}


def is_transient_gemini_error(e: Exception) -> bool:
    """Filter to transient/retryable Gemini API errors only. The google-genai
    SDK (unlike the deprecated google-generativeai/api_core one) doesn't
    expose distinct exception classes per status — every HTTP error is a
    genai_errors.APIError with a `.code` attribute, so filter on that."""
    return isinstance(e, genai_errors.APIError) and e.code in _TRANSIENT_STATUS_CODES
