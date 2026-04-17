import unittest

from securefetch import ClientError, DecodeError, Headers, Response, ServerError


class HeadersTests(unittest.TestCase):
    def test_case_insensitive(self) -> None:
        headers = Headers([("Content-Type", "text/plain")])
        self.assertEqual(headers["content-type"], "text/plain")
        self.assertIn("CONTENT-TYPE", headers)
        self.assertIsNone(headers.get("missing"))

    def test_repeated_headers(self) -> None:
        headers = Headers([("Set-Cookie", "a=1"), ("set-cookie", "b=2"), ("X", "y")])
        self.assertEqual(headers.get_all("Set-Cookie"), ["a=1", "b=2"])
        self.assertEqual(headers["Set-Cookie"], "a=1, b=2")
        self.assertEqual(len(headers), 2)
        self.assertEqual(list(headers), ["Set-Cookie", "X"])


class ResponseTests(unittest.TestCase):
    def make(self, status: int = 200, body: bytes = b"", ctype: str = "") -> Response:
        headers = Headers([("Content-Type", ctype)] if ctype else [])
        return Response(status, "Reason", "http://test/", headers, body)

    def test_text_defaults_to_utf8(self) -> None:
        self.assertEqual(self.make(body="héllo".encode()).text, "héllo")

    def test_unknown_charset_falls_back(self) -> None:
        response = self.make(body=b"hi", ctype="text/plain; charset=made-up")
        self.assertEqual(response.text, "hi")

    def test_json(self) -> None:
        self.assertEqual(self.make(body=b'{"a": [1, 2]}').json(), {"a": [1, 2]})
        with self.assertRaises(DecodeError):
            self.make(body=b"nope").json()

    def test_raise_for_status(self) -> None:
        self.make(200).raise_for_status()
        self.make(302).raise_for_status()
        with self.assertRaises(ClientError):
            self.make(404).raise_for_status()
        with self.assertRaises(ServerError) as ctx:
            self.make(502).raise_for_status()
        self.assertIn("502 Reason for http://test/", str(ctx.exception))

    def test_ok(self) -> None:
        self.assertTrue(self.make(204).ok)
        self.assertFalse(self.make(400).ok)


if __name__ == "__main__":
    unittest.main()
