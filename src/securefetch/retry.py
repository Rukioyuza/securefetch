"""Retry policy with exponential backoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

__all__ = ["RetryPolicy", "parse_retry_after"]

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE"})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Turn a Retry-After header into a number of seconds.

    The header may be a number of seconds or an HTTP date. Returns None
    when the header is missing or cannot be parsed.
    """
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (when - now).total_seconds())


@dataclass(frozen=True)
class RetryPolicy:
    """When and how long to wait before trying a request again.

    total: how many retries after the first attempt (0 turns retries off).
    backoff_factor: the first delay in seconds; it doubles on each retry.
    max_backoff: upper limit for any single delay, including Retry-After.
    statuses: response codes worth retrying.
    methods: methods retried on connection errors and 5xx. A 429 is
        retried for any method because the server did not process it.
    """

    total: int = 3
    backoff_factor: float = 0.5
    max_backoff: float = 30.0
    statuses: frozenset[int] = RETRY_STATUSES
    methods: frozenset[str] = IDEMPOTENT_METHODS

    def __post_init__(self) -> None:
        if self.total < 0:
            raise ValueError("total must be 0 or more")
        if self.backoff_factor < 0 or self.max_backoff < 0:
            raise ValueError("backoff values must not be negative")

    def backoff(self, retry_number: int) -> float:
        """Delay before retry number `retry_number` (counting from 0)."""
        return min(self.max_backoff, self.backoff_factor * 2.0**retry_number)

    def delay(self, retry_number: int, retry_after: str | None = None) -> float:
        """Delay to use, preferring the server's Retry-After when given."""
        seconds = parse_retry_after(retry_after)
        if seconds is None:
            return self.backoff(retry_number)
        return min(self.max_backoff, seconds)

    def can_retry_error(self, method: str) -> bool:
        """Whether a connection error for this method may be retried."""
        return method.upper() in self.methods

    def can_retry_status(self, method: str, status: int) -> bool:
        """Whether a response with this status may be retried."""
        if status not in self.statuses:
            return False
        return status == 429 or method.upper() in self.methods


NO_RETRIES = RetryPolicy(total=0)
