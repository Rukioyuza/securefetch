"""securefetch: a small HTTPS client built on the standard library."""

from .errors import (
    ClientError,
    ConnectionFailed,
    DecodeError,
    HTTPError,
    InvalidURL,
    RedirectError,
    RequestTimeout,
    SecureFetchError,
    ServerError,
    TLSError,
)
from .response import Headers, Response
from .retry import RetryPolicy
from .session import Session
from .tls import create_ssl_context

__all__ = [
    "ClientError",
    "ConnectionFailed",
    "DecodeError",
    "HTTPError",
    "Headers",
    "InvalidURL",
    "RedirectError",
    "RequestTimeout",
    "Response",
    "RetryPolicy",
    "SecureFetchError",
    "ServerError",
    "Session",
    "TLSError",
    "create_ssl_context",
]

__version__ = "0.1.0"
