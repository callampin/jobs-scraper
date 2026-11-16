import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from common.http import PoliteHttpClient


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = 0
        self.last_method = None

    def get(self, url, **kwargs):
        self.calls += 1
        self.last_method = "GET"
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls += 1
        self.last_method = "POST"
        return self.responses.pop(0)


def response(status, body=b'{"ok": true}', retry_after=None):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result.url = "https://example.test/api"
    if retry_after is not None:
        result.headers["Retry-After"] = retry_after
    return result


class HttpTests(unittest.TestCase):
    def test_retries_429_with_retry_after_and_returns_json(self):
        session = FakeSession([response(429, retry_after="3"), response(200)])
        sleeps = []
        client = PoliteHttpClient(
            user_agent="test-agent",
            delay_seconds=1,
            max_retries=1,
            backoff_seconds=2,
            session=session,
            sleep=sleeps.append,
            monotonic=lambda: 0.0,
        )

        self.assertEqual(client.get_json("https://example.test/api"), {"ok": True})
        self.assertEqual(session.calls, 2)
        self.assertEqual(sleeps, [3.0, 1.0])
        self.assertEqual(session.headers["User-Agent"], "test-agent")

    def test_does_not_retry_client_errors(self):
        session = FakeSession([response(403, body=b"{}")])
        client = PoliteHttpClient(
            user_agent="test-agent",
            delay_seconds=1,
            max_retries=4,
            session=session,
            sleep=lambda _: None,
            monotonic=lambda: 0.0,
        )

        with self.assertRaises(requests.HTTPError):
            client.get("https://example.test/api")
        self.assertEqual(session.calls, 1)

    def test_post_json_uses_post_and_shared_retry_behavior(self):
        session = FakeSession([response(200, body=b'{"total": 2}')])
        sleeps = []
        client = PoliteHttpClient(
            user_agent="test-agent",
            delay_seconds=1,
            max_retries=0,
            session=session,
            sleep=sleeps.append,
            monotonic=lambda: 0.0,
        )

        result = client.post_json(
            "https://example.test/api",
            json={"query": "python"},
            headers={"x-site-id": "TEST"},
        )
        self.assertEqual(result, {"total": 2})
        self.assertEqual(session.last_method, "POST")
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
