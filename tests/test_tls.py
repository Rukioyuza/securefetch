import ssl
import tempfile
import unittest
import urllib.request
from email.message import Message
from io import BytesIO
from pathlib import Path

from local_server import CERT_FILE, LocalServer

from securefetch import RedirectError, Session, TLSError, create_ssl_context
from securefetch.session import _SafeRedirectHandler


class SSLContextTests(unittest.TestCase):
    def test_default_context_verifies(self) -> None:
        context = create_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_custom_ca_bundle_file(self) -> None:
        context = create_ssl_context(CERT_FILE)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.cert_store_stats()["x509_ca"], 1)

    def test_custom_ca_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            context = create_ssl_context(folder)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_missing_ca_bundle(self) -> None:
        with self.assertRaises(FileNotFoundError):
            create_ssl_context(Path("does/not/exist.pem"))

    def test_session_uses_the_context(self) -> None:
        session = Session(ca_bundle=CERT_FILE, trust_env=False)
        self.assertEqual(session.ssl_context.cert_store_stats()["x509_ca"], 1)


class HTTPSTests(unittest.TestCase):
    """End to end over TLS against a self-signed cert for 127.0.0.1."""

    def test_untrusted_certificate_is_rejected(self) -> None:
        sleeps: list[float] = []
        with LocalServer(tls=True) as server:
            session = Session(server.url, trust_env=False, sleep=sleeps.append)
            with self.assertRaises(TLSError):
                session.get("/echo")
        self.assertEqual(sleeps, [], "TLS errors should not be retried")

    def test_custom_ca_bundle_is_trusted(self) -> None:
        with LocalServer(tls=True) as server:
            session = Session(server.url, ca_bundle=CERT_FILE, trust_env=False)
            self.assertEqual(session.get_json("/echo")["path"], "/echo")


class RedirectHandlerTests(unittest.TestCase):
    def redirect(self, old: str, new: str) -> urllib.request.Request | None:
        request = urllib.request.Request(old, headers={"Authorization": "x"})
        return _SafeRedirectHandler().redirect_request(
            request, BytesIO(), 302, "Found", Message(), new
        )

    def test_https_to_http_is_refused(self) -> None:
        with self.assertRaises(RedirectError):
            self.redirect("https://example.com/a", "http://example.com/b")

    def test_other_schemes_are_refused(self) -> None:
        with self.assertRaises(RedirectError):
            self.redirect("http://example.com/a", "ftp://example.com/b")

    def test_http_to_https_is_allowed(self) -> None:
        new = self.redirect("http://example.com/a", "https://example.com/b")
        assert new is not None
        self.assertEqual(new.full_url, "https://example.com/b")

    def test_authorization_dropped_for_other_host(self) -> None:
        new = self.redirect("https://example.com/a", "https://other.example/b")
        assert new is not None
        self.assertFalse(new.has_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
