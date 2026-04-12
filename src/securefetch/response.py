"""Response and header types."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from email.message import Message
from typing import Any

from .errors import ClientError, DecodeError, ServerError

__all__ = ["Headers", "Response"]


class Headers(Mapping[str, str]):
    """Case-insensitive, read-only header mapping.

    Repeated headers are joined with ", " when read by key; use
    get_all() to see each value separately.
    """

    def __init__(self, items: Iterable[tuple[str, str]] = ()) -> None:
        self._items = [(str(k), str(v)) for k, v in items]

    def __getitem__(self, key: str) -> str:
        values = self.get_all(key)
        if not values:
            raise KeyError(key)
        return ", ".join(values)

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for key, _ in self._items:
            if key.lower() not in seen:
                seen.add(key.lower())
                yield key

    def __len__(self) -> int:
        return len({k.lower() for k, _ in self._items})

    def __repr__(self) -> str:
        return f"Headers({self._items!r})"

    def get_all(self, key: str) -> list[str]:
        """Return every value sent for this header."""
        lower = key.lower()
        return [v for k, v in self._items if k.lower() == lower]


def _charset(content_type: str | None) -> str:
    if not content_type:
        return "utf-8"
    message = Message()
    message["Content-Type"] = content_type
    return message.get_content_charset() or "utf-8"


@dataclass
class Response:
    """An HTTP response with the body already read."""

    status: int
    reason: str
    url: str
    headers: Headers = field(default_factory=Headers)
    content: bytes = b""

    @property
    def ok(self) -> bool:
        """True for status codes below 400."""
        return self.status < 400

    @property
    def text(self) -> str:
        """The body decoded using the charset from Content-Type."""
        charset = _charset(self.headers.get("Content-Type"))
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Parse the body as JSON."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            message = f"response from {self.url} is not valid JSON: {exc}"
            raise DecodeError(message) from exc

    def raise_for_status(self) -> None:
        """Raise ClientError or ServerError for 4xx and 5xx responses."""
        if 400 <= self.status < 500:
            raise ClientError(self)
        if self.status >= 500:
            raise ServerError(self)

    def __repr__(self) -> str:
        return f"<Response [{self.status}] {self.url}>"
