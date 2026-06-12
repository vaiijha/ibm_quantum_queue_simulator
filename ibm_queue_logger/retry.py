"""Retry helper for transient API / rate-limit errors."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

_RETRYABLE_STATUS_CODES = {429, 503}
_RETRYABLE_KEYWORDS = (
    "429",
    "503",
    "too many requests",
    "rate limit",
    "connection",
    "timeout",
    "temporarily unavailable",
)


def _parse_retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    header = None
    if hasattr(response, "headers"):
        header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except (TypeError, ValueError):
        return None


def _is_retryable(exc: BaseException) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in _RETRYABLE_STATUS_CODES:
        return True

    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) in _RETRYABLE_STATUS_CODES:
        return True

    message = str(exc).lower()
    return any(keyword in message for keyword in _RETRYABLE_KEYWORDS)


def with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> T:
    """Call fn with exponential backoff on transient / rate-limit failures."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            retry_after = _parse_retry_after(exc)
            delay = retry_after if retry_after is not None else base_delay * (2**attempt)
            time.sleep(delay)
            attempt += 1
