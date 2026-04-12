"""Exception types raised by securefetch."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .response import Response

__all__ = [
    "ClientError",
    "ConnectionFailed",
    "DecodeError",
    "HTTPError",
    "InvalidURL",
    "RedirectError",
    "RequestTimeout",
    "SecureFetchError",
    "ServerError",
    "TLSError",
]


class SecureFetchError(Exception):
    """Base class for every error raised by securefetch."""


class InvalidURL(SecureFetchError, ValueError):
    """The URL is malformed or uses a scheme other than http/https."""


class ConnectionFailed(SecureFetchError):
    """The connection could not be made or was dropped."""


class RequestTimeout(ConnectionFailed):
    """The server did not respond within the timeout."""


class TLSError(ConnectionFailed):
    """The TLS handshake failed, usually a certificate problem.

    These are never retried.
    """


class RedirectError(SecureFetchError):
    """A redirect was refused, for example https to http."""


class DecodeError(SecureFetchError, ValueError):
    """The response body could not be decoded as JSON."""


class HTTPError(SecureFetchError):
    """The server answered with a 4xx or 5xx status."""

    def __init__(self, response: Response) -> None:
        self.response = response
        self.status = response.status
        super().__init__(f"{response.status} {response.reason} for {response.url}")


class ClientError(HTTPError):
    """A 4xx response."""


class ServerError(HTTPError):
    """A 5xx response."""
