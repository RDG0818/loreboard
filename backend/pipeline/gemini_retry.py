from google.api_core import exceptions as google_exceptions


def is_transient_gemini_error(e: Exception) -> bool:
    """Filter to transient/retryable Gemini API errors only."""
    return isinstance(
        e,
        (
            google_exceptions.ResourceExhausted,
            google_exceptions.ServiceUnavailable,
            google_exceptions.DeadlineExceeded,
        ),
    )
