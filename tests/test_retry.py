import unittest
from datetime import datetime, timezone

from securefetch import RetryPolicy
from securefetch.retry import parse_retry_after


class ParseRetryAfterTests(unittest.TestCase):
    def test_seconds(self) -> None:
        self.assertEqual(parse_retry_after("120"), 120.0)
        self.assertEqual(parse_retry_after(" 5 "), 5.0)

    def test_http_date(self) -> None:
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        value = "Mon, 01 Jan 2024 12:00:30 GMT"
        self.assertEqual(parse_retry_after(value, now=now), 30.0)

    def test_date_in_the_past_is_zero(self) -> None:
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        value = "Mon, 01 Jan 2024 11:00:00 GMT"
        self.assertEqual(parse_retry_after(value, now=now), 0.0)

    def test_missing_or_bad(self) -> None:
        self.assertIsNone(parse_retry_after(None))
        self.assertIsNone(parse_retry_after("soon"))
        self.assertIsNone(parse_retry_after("-5"))


class RetryPolicyTests(unittest.TestCase):
    def test_backoff_doubles_and_is_capped(self) -> None:
        policy = RetryPolicy(backoff_factor=0.5, max_backoff=3.0)
        delays = [policy.backoff(n) for n in range(5)]
        self.assertEqual(delays, [0.5, 1.0, 2.0, 3.0, 3.0])

    def test_delay_prefers_retry_after(self) -> None:
        policy = RetryPolicy(backoff_factor=0.5, max_backoff=60)
        self.assertEqual(policy.delay(0, "10"), 10.0)
        self.assertEqual(policy.delay(2, None), 2.0)
        self.assertEqual(policy.delay(2, "garbage"), 2.0)
        self.assertEqual(policy.delay(0, "600"), 60.0)

    def test_which_methods_retry(self) -> None:
        policy = RetryPolicy()
        self.assertTrue(policy.can_retry_error("get"))
        self.assertFalse(policy.can_retry_error("POST"))
        self.assertTrue(policy.can_retry_status("GET", 503))
        self.assertFalse(policy.can_retry_status("POST", 503))
        self.assertTrue(policy.can_retry_status("POST", 429))
        self.assertFalse(policy.can_retry_status("GET", 404))

    def test_rejects_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(total=-1)
        with self.assertRaises(ValueError):
            RetryPolicy(backoff_factor=-1)


if __name__ == "__main__":
    unittest.main()
