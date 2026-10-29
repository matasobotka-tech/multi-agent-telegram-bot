import logging
import os
import unittest
from unittest import mock

from bot import main


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        main._hits.clear()

    def test_limit_per_minute(self):
        results = [main.allowed(1, now=1000 + i) for i in range(main.RATE_LIMIT + 1)]
        self.assertTrue(all(results[:-1]))
        self.assertFalse(results[-1])

    def test_window_resets(self):
        for i in range(main.RATE_LIMIT + 1):
            main.allowed(1, now=1000 + i)
        self.assertTrue(main.allowed(1, now=1100))

    def test_chats_are_independent(self):
        for i in range(main.RATE_LIMIT + 1):
            main.allowed(1, now=1000 + i)
        self.assertTrue(main.allowed(2, now=1010))

    def test_idle_chats_are_forgotten(self):
        main.allowed(1, now=1000)
        main.allowed(2, now=1100)
        self.assertNotIn(1, main._hits)


class AllowlistTests(unittest.TestCase):
    def test_empty_means_everyone(self):
        with mock.patch.dict(os.environ, {"ALLOWED_CHAT_IDS": ""}):
            self.assertEqual(main.allowed_chats(), set())

    def test_parses_ids_and_ignores_junk(self):
        with mock.patch.dict(os.environ, {"ALLOWED_CHAT_IDS": "123, -100456,abc,"}):
            self.assertEqual(main.allowed_chats(), {123, -100456})


class SecretTests(unittest.TestCase):
    def test_request_urls_with_token_are_not_logged(self):
        self.assertGreaterEqual(logging.getLogger("httpx").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
