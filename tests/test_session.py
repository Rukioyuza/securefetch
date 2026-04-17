import unittest

from local_server import LocalServer

from securefetch import (
    ClientError,
    ConnectionFailed,
    DecodeError,
    HTTPError,
    InvalidURL,
    RequestTimeout,
    RetryPolicy,
    ServerError,
    Session,
)


class SessionTestCase(unittest.TestCase):
    """Starts a local server and records sleeps instead of waiting."""

    def setUp(self) -> None:
        self.server = LocalServer()
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.sleeps: list[float] = []

    def session(self, **kwargs) -> Session:
        kwargs.setdefault("trust_env", False)
        kwargs.setdefault("sleep", self.sleeps.append)
        return Session(self.server.url, **kwargs)


class BasicRequestTests(SessionTestCase):
    def test_get_relative_to_base_url(self) -> None:
        data = self.session().get_json("/echo/items")
        self.assertEqual(data["method"], "GET")
        self.assertEqual(data["path"], "/echo/items")
        self.assertEqual(data["headers"]["accept"], "application/json")

    def test_base_url_with_path_prefix(self) -> None:
        session = Session(f"{self.server.url}/api/v1/", trust_env=False)
        self.assertEqual(session.get_json("users")["path"], "/api/v1/users")
        self.assertEqual(session.get_json("/users")["path"], "/api/v1/users")

    def test_absolute_url_ignores_base(self) -> None:
        session = Session("https://example.invalid", trust_env=False)
        data = session.get_json(f"{self.server.url}/elsewhere")
        self.assertEqual(data["path"], "/elsewhere")

    def test_query_params(self) -> None:
        params = {"q": "cats", "tag": ["x", "y"]}
        data = self.session().get_json("/search?a=1", params=params)
        self.assertEqual(data["query"], {"a": ["1"], "q": ["cats"], "tag": ["x", "y"]})

    def test_default_and_request_headers(self) -> None:
        session = self.session(headers={"X-Team": "red", "User-Agent": "tests"})
        data = session.get_json("/echo", headers={"x-team": "blue", "X-Extra": "1"})
        headers = data["headers"]
        self.assertEqual(headers["x-team"], "blue")
        self.assertEqual(headers["x-extra"], "1")
        self.assertEqual(headers["user-agent"], "tests")

    def test_default_user_agent(self) -> None:
        data = self.session().get_json("/echo")
        self.assertTrue(data["headers"]["user-agent"].startswith("securefetch/"))

    def test_post_json(self) -> None:
        data = self.session().post_json("/echo", {"name": "ada", "id": 1})
        self.assertEqual(data["method"], "POST")
        self.assertEqual(data["headers"]["content-type"], "application/json")
        self.assertEqual(data["body"], '{"name": "ada", "id": 1}')

    def test_form_data(self) -> None:
        data = self.session().post("/echo", data={"a": "1", "b": "two words"}).json()
        self.assertEqual(data["body"], "a=1&b=two+words")
        self.assertEqual(
            data["headers"]["content-type"], "application/x-www-form-urlencoded"
        )

    def test_json_and_data_together_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            self.session().post("/echo", json={}, data=b"x")

    def test_other_methods(self) -> None:
        session = self.session()
        for method in ("put", "patch", "delete"):
            data = getattr(session, method)("/echo").json()
            self.assertEqual(data["method"], method.upper())
        response = session.head("/echo")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content, b"")

    def test_response_fields(self) -> None:
        response = self.session().get("/echo")
        self.assertTrue(response.ok)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.url, f"{self.server.url}/echo")
        self.assertEqual(response.headers["content-type"], "application/json")

    def test_charset_from_content_type(self) -> None:
        self.assertEqual(self.session().get("/latin1").text, "café")

    def test_bad_json_raises_decode_error(self) -> None:
        response = self.session().get("/not-json")
        with self.assertRaises(DecodeError):
            response.json()

    def test_follows_redirects(self) -> None:
        response = self.session().get("/redirect")
        self.assertEqual(response.url, f"{self.server.url}/echo")
        self.assertEqual(response.json()["path"], "/echo")

    def test_invalid_urls(self) -> None:
        with self.assertRaises(InvalidURL):
            Session("ftp://example.com")
        with self.assertRaises(InvalidURL):
            Session(trust_env=False).get("file:///etc/passwd")
        with self.assertRaises(InvalidURL):
            Session(trust_env=False).get("/relative/without/base")


class CookieTests(SessionTestCase):
    def test_cookies_are_kept_between_requests(self) -> None:
        session = self.session()
        session.get("/set-cookie")
        self.assertEqual([c.name for c in session.cookies], ["session"])
        data = session.get_json("/echo")
        self.assertEqual(data["headers"]["cookie"], "session=abc123")

    def test_sessions_do_not_share_cookies(self) -> None:
        self.session().get("/set-cookie")
        data = self.session().get_json("/echo")
        self.assertNotIn("cookie", data["headers"])


class StatusErrorTests(SessionTestCase):
    def test_4xx_raises_client_error(self) -> None:
        with self.assertRaises(ClientError) as ctx:
            self.session().get("/not-found")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.response.json(), {"error": "missing"})
        self.assertIsInstance(ctx.exception, HTTPError)

    def test_5xx_raises_server_error_after_retries(self) -> None:
        with self.assertRaises(ServerError):
            self.session(retry=RetryPolicy(total=2)).get("/always-500")
        self.assertEqual(self.server.hits["/always-500"], 3)

    def test_raise_for_status_can_be_turned_off(self) -> None:
        session = self.session(raise_for_status=False, retry=RetryPolicy(total=0))
        response = session.get("/always-500")
        self.assertFalse(response.ok)
        self.assertEqual(response.status, 500)


class RetryTests(SessionTestCase):
    def test_retries_503_with_exponential_backoff(self) -> None:
        session = self.session(retry=RetryPolicy(total=3, backoff_factor=0.5))
        self.assertEqual(session.get_json("/flaky"), {"attempts": 3})
        self.assertEqual(self.sleeps, [0.5, 1.0])

    def test_gives_up_after_total_retries(self) -> None:
        session = self.session(retry=RetryPolicy(total=1))
        with self.assertRaises(ServerError):
            session.get("/flaky")
        self.assertEqual(self.server.hits["/flaky"], 2)

    def test_respects_retry_after(self) -> None:
        session = self.session(retry=RetryPolicy(total=2, backoff_factor=0.1))
        self.assertEqual(session.get_json("/rate-limited"), {"attempts": 2})
        self.assertEqual(self.sleeps, [7.0])

    def test_retry_after_is_capped(self) -> None:
        session = self.session(retry=RetryPolicy(total=2, max_backoff=2.0))
        session.get("/rate-limited")
        self.assertEqual(self.sleeps, [2.0])

    def test_429_is_retried_for_post(self) -> None:
        self.assertEqual(self.session().post_json("/rate-limited", {}), {"attempts": 2})

    def test_5xx_is_not_retried_for_post(self) -> None:
        with self.assertRaises(ServerError):
            self.session().post("/flaky", json={})
        self.assertEqual(self.server.hits["/flaky"], 1)
        self.assertEqual(self.sleeps, [])

    def test_connection_errors_are_retried(self) -> None:
        session = self.session(retry=RetryPolicy(total=2, backoff_factor=1.0))
        with self.assertRaises(ConnectionFailed):
            session.get("/drop")
        self.assertEqual(self.server.hits["/drop"], 3)
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_timeout(self) -> None:
        session = self.session(timeout=0.2, retry=RetryPolicy(total=0))
        with self.assertRaises(RequestTimeout):
            session.get("/slow")

    def test_request_timeout_overrides_session(self) -> None:
        session = self.session(timeout=0.1, retry=RetryPolicy(total=0))
        self.assertTrue(session.get("/slow", timeout=5).ok)


class RedirectSafetyTests(SessionTestCase):
    def test_credentials_dropped_on_cross_host_redirect(self) -> None:
        with LocalServer() as other:
            target = f"{other.url}/echo"
            data = self.session(
                headers={"Authorization": "Bearer secret", "Cookie": "a=b"}
            ).get_json("/redirect-to", params={"url": target})
        self.assertEqual(data["path"], "/echo")
        self.assertNotIn("authorization", data["headers"])
        self.assertNotIn("cookie", data["headers"])

    def test_credentials_kept_on_same_host_redirect(self) -> None:
        session = self.session(headers={"Authorization": "Bearer secret"})
        data = session.get_json("/redirect")
        self.assertEqual(data["headers"]["authorization"], "Bearer secret")


if __name__ == "__main__":
    unittest.main()
