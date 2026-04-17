"""A small HTTP(S) server on 127.0.0.1 for the tests. No network needed."""

from __future__ import annotations

import json
import ssl
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

CERT_DIR = Path(__file__).resolve().parent / "certs"
CERT_FILE = CERT_DIR / "localhost.pem"
KEY_FILE = CERT_DIR / "localhost-key.pem"


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep test output quiet

    def send_json(
        self, status: int, payload: object, headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, status: int, text: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(text)))
        self.end_headers()
        self.wfile.write(text)

    def echo(self, body: str) -> None:
        url = urlsplit(self.path)
        self.send_json(
            200,
            {
                "method": self.command,
                "path": url.path,
                "query": parse_qs(url.query),
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            },
        )

    def handle_any(self) -> None:
        # Always read the request body first. Replying with unread data left
        # on the socket makes Windows reset the connection.
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        path = urlsplit(self.path).path
        hits = self.server.count(path)

        if path == "/set-cookie":
            self.send_response(204)
            self.send_header("Set-Cookie", "session=abc123; Path=/")
            self.end_headers()
        elif path == "/flaky":
            # Fails twice with 503, then works.
            if hits <= 2:
                self.send_json(503, {"error": "busy"})
            else:
                self.send_json(200, {"attempts": hits})
        elif path == "/rate-limited":
            if hits == 1:
                self.send_json(429, {"error": "slow down"}, {"Retry-After": "7"})
            else:
                self.send_json(200, {"attempts": hits})
        elif path == "/always-500":
            self.send_json(500, {"error": "broken"})
        elif path == "/not-found":
            self.send_json(404, {"error": "missing"})
        elif path == "/drop":
            # Close the connection without sending anything.
            self.close_connection = True
        elif path == "/slow":
            time.sleep(1.0)
            self.send_json(200, {})
        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/echo")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/redirect-to":
            target = parse_qs(urlsplit(self.path).query)["url"][0]
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/latin1":
            body = "café".encode("latin-1")
            self.send_text(200, body, "text/plain; charset=iso-8859-1")
        elif path == "/not-json":
            self.send_text(200, b"<html></html>", "text/html")
        else:
            self.echo(body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = handle_any


class LocalServer(ThreadingHTTPServer):
    """Runs Handler in a background thread and counts hits per path."""

    daemon_threads = True

    def __init__(self, tls: bool = False) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.hits: Counter[str] = Counter()
        self._lock = threading.Lock()
        self.scheme = "http"
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(CERT_FILE, KEY_FILE)
            self.socket = context.wrap_socket(self.socket, server_side=True)
            self.scheme = "https"
        self._thread = threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    def handle_error(self, request: object, client_address: object) -> None:
        pass  # clients hanging up early (timeouts, TLS failures) is expected

    def count(self, path: str) -> int:
        with self._lock:
            self.hits[path] += 1
            return self.hits[path]

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"{self.scheme}://{host}:{port}"

    def __enter__(self) -> LocalServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join()
