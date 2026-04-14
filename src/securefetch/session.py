"""The Session class: shared settings, cookies and retries."""

from __future__ import annotations

import http.client
import http.cookiejar
import json as jsonlib
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import IO, Any

from .errors import (
    ConnectionFailed,
    InvalidURL,
    RedirectError,
    RequestTimeout,
    TLSError,
)
from .response import Headers, Response
from .retry import RetryPolicy
from .tls import create_ssl_context

__all__ = ["Session"]

USER_AGENT = "securefetch/0.1"
DEFAULT_TIMEOUT = 10.0

Params = Mapping[str, Any]
Body = bytes | str | Mapping[str, Any]

# Headers that must not follow a redirect to a different host.
_SENSITIVE_HEADERS = ("Authorization", "Cookie", "Proxy-authorization")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows redirects, but never from https to http or to other schemes.

    Credentials are dropped when a redirect goes to a different host.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        problem = None
        if new.scheme not in ("http", "https"):
            problem = f"refusing to follow redirect to {new.scheme!r} URL"
        elif old.scheme == "https" and new.scheme == "http":
            problem = "refusing to follow redirect from https to http"
        if problem is not None:
            fp.close()
            raise RedirectError(f"{problem}: {newurl}")

        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None and old.netloc.lower() != new.netloc.lower():
            for name in _SENSITIVE_HEADERS:
                new_req.remove_header(name)
        return new_req


def _merge_headers(*sources: Mapping[str, str] | None) -> dict[str, str]:
    """Merge header dicts; later sources win, names compared case-insensitively."""
    merged: dict[str, tuple[str, str]] = {}
    for source in sources:
        for name, value in (source or {}).items():
            merged[name.lower()] = (name, value)
    return dict(merged.values())


def _has_header(headers: Mapping[str, str], name: str) -> bool:
    return any(key.lower() == name.lower() for key in headers)


class Session:
    """Sends HTTP(S) requests with shared settings.

    Relative URLs are joined onto base_url. Cookies set by the server are
    kept and sent back on later requests to the same site. Certificates
    are always verified; pass ca_bundle to trust a custom CA.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: RetryPolicy | None = None,
        ca_bundle: str | os.PathLike[str] | None = None,
        raise_for_status: bool = True,
        trust_env: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if base_url is not None:
            _check_url(base_url)
        self.base_url = base_url
        self.headers: dict[str, str] = _merge_headers(
            {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}, headers
        )
        self.timeout = timeout
        self.retry = retry if retry is not None else RetryPolicy()
        self.raise_for_status = raise_for_status
        self.cookies = http.cookiejar.CookieJar()
        self.ssl_context: ssl.SSLContext = create_ssl_context(ca_bundle)
        self._sleep = sleep

        # trust_env=False ignores proxy settings from the environment.
        proxies: dict[str, str] | None = None if trust_env else {}
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            urllib.request.HTTPSHandler(context=self.ssl_context),
            urllib.request.HTTPCookieProcessor(self.cookies),
            _SafeRedirectHandler(),
        )

    def build_url(self, url: str, params: Params | None = None) -> str:
        """Resolve url against base_url and append query parameters."""
        if self.base_url and not urllib.parse.urlsplit(url).scheme:
            url = self.base_url.rstrip("/") + "/" + url.lstrip("/")
        _check_url(url)
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            url += ("&" if urllib.parse.urlsplit(url).query else "?") + query
        return url

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Params | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: Body | None = None,
        timeout: float | None = None,
    ) -> Response:
        """Send a request, retrying according to the session's RetryPolicy."""
        method = method.upper()
        full_url = self.build_url(url, params)
        all_headers = _merge_headers(self.headers, headers)
        body = self._encode_body(all_headers, json, data)
        timeout = self.timeout if timeout is None else timeout

        retry_number = 0
        while True:
            can_retry = retry_number < self.retry.total
            try:
                response = self._send(method, full_url, all_headers, body, timeout)
            except TLSError:
                raise
            except ConnectionFailed:
                if not (can_retry and self.retry.can_retry_error(method)):
                    raise
                self._sleep(self.retry.backoff(retry_number))
                retry_number += 1
                continue

            if can_retry and self.retry.can_retry_status(method, response.status):
                retry_after = response.headers.get("Retry-After")
                self._sleep(self.retry.delay(retry_number, retry_after))
                retry_number += 1
                continue
            break

        if self.raise_for_status:
            response.raise_for_status()
        return response

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> Response:
        return self.request("HEAD", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """GET a URL and return the parsed JSON body."""
        extra = kwargs.pop("headers", None)
        headers = _merge_headers({"Accept": "application/json"}, extra)
        return self.get(url, headers=headers, **kwargs).json()

    def post_json(self, url: str, payload: Any, **kwargs: Any) -> Any:
        """POST `payload` as JSON and return the parsed JSON reply."""
        return self.post(url, json=payload, **kwargs).json()

    @staticmethod
    def _encode_body(
        headers: dict[str, str], json: Any, data: Body | None
    ) -> bytes | None:
        if json is not None and data is not None:
            raise ValueError("pass either json or data, not both")
        if json is not None:
            if not _has_header(headers, "Content-Type"):
                headers["Content-Type"] = "application/json"
            if not _has_header(headers, "Accept"):
                headers["Accept"] = "application/json"
            return jsonlib.dumps(json).encode("utf-8")
        if isinstance(data, Mapping):
            if not _has_header(headers, "Content-Type"):
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            return urllib.parse.urlencode(data, doseq=True).encode("ascii")
        if isinstance(data, str):
            return data.encode("utf-8")
        return data

    def _send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Response:
        """Make a single attempt and turn low level errors into ours."""
        request = urllib.request.Request(
            url, data=body, headers=dict(headers), method=method
        )
        try:
            with self._opener.open(request, timeout=timeout) as raw:
                content = raw.read()
                return Response(
                    raw.status,
                    raw.reason,
                    raw.url,
                    Headers(raw.headers.items()),
                    content,
                )
        except urllib.error.HTTPError as exc:
            # urllib raises for 4xx/5xx; we want a normal Response instead.
            with exc:
                content = exc.read()
            return Response(
                exc.code,
                str(exc.reason),
                exc.filename or url,
                Headers(exc.headers.items()),
                content,
            )
        except urllib.error.URLError as exc:
            raise _convert_error(exc.reason, url) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise _convert_error(exc, url) from exc


def _convert_error(reason: object, url: str) -> ConnectionFailed:
    if isinstance(reason, ssl.SSLError):
        return TLSError(f"TLS error for {url}: {reason}")
    if isinstance(reason, TimeoutError):
        return RequestTimeout(f"timed out waiting for {url}")
    return ConnectionFailed(f"connection to {url} failed: {reason}")


def _check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise InvalidURL(f"only http and https URLs are supported: {url!r}")
    if not parts.netloc:
        raise InvalidURL(f"URL has no host: {url!r}")
