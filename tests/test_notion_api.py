"""Tests for the read-only Notion REST adapter (fake transport; no network)."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from adapters.notion_api import (
    NotionAPIError,
    NotionConfig,
    NotionConfigurationError,
    NotionReadClient,
    RateLimiter,
    all_of,
    config_from_env,
    date_range_filter,
    main,
    normalize_id,
    prop_filter,
    simplify_page,
)

DS = "382f5aa7-302a-45aa-ae94-e87513fb94e1"
DB = "85f6c9342bb343f1aa5d23522a476134"
TOKEN = "secret_test_token_value"


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, _n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status, code="rate_limited", retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    body = io.BytesIO(json.dumps({"code": code, "message": "slow down"}).encode())
    return HTTPError("https://api.notion.com/v1/x", status, "err", headers, body)


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(responses, rps=3.0):
    clock = FakeClock()
    opener = FakeOpener(responses)
    limiter = RateLimiter(rps, clock=clock.clock, sleep=clock.sleep)
    client = NotionReadClient(NotionConfig(token=TOKEN, requests_per_second=rps),
                              opener=opener, limiter=limiter, sleep=clock.sleep)
    return client, opener, clock


class ConfigTests(unittest.TestCase):
    def test_missing_token_fails_closed(self):
        with patch.dict(os.environ, {"NOTION_TOKEN": ""}, clear=False):
            with self.assertRaises(NotionConfigurationError):
                config_from_env()

    def test_rps_above_documented_average_is_rejected(self):
        with patch.dict(os.environ, {"NOTION_TOKEN": "x", "NOTION_MAX_RPS": "5"}, clear=False):
            with self.assertRaises(NotionConfigurationError):
                config_from_env()

    def test_normalize_id_accepts_urls_and_collection_uris(self):
        self.assertEqual(normalize_id(f"collection://{DS}"), DS)
        self.assertEqual(
            normalize_id(f"https://app.notion.com/p/ydonchoi/{DB}?v=c804d511d051469eb32094b64a5ee39a"),
            "85f6c934-2bb3-43f1-aa5d-23522a476134",
        )
        with self.assertRaises(ValueError):
            normalize_id("not-an-id")


class FilterTests(unittest.TestCase):
    def test_filter_shapes_match_notion_rest_format(self):
        f = all_of(prop_filter("Lifecycle State", "select", "equals", "ACTIVE"),
                   date_range_filter("Deadline", "2026-11-01", "2026-11-30"))
        self.assertEqual(f["and"][0], {"property": "Lifecycle State", "select": {"equals": "ACTIVE"}})
        self.assertEqual(f["and"][1]["and"][0], {"property": "Deadline", "date": {"on_or_after": "2026-11-01"}})
        self.assertEqual(date_range_filter("D", start="2026-01-01"),
                         {"property": "D", "date": {"on_or_after": "2026-01-01"}})


class ClientTests(unittest.TestCase):
    def test_query_sends_server_side_filter_and_caps_pages(self):
        pages = [{"results": [{"id": str(i)}], "has_more": True, "next_cursor": f"c{i}"} for i in range(3)]
        client, opener, _ = make_client(pages)
        flt = prop_filter("Status", "status", "equals", "Open")
        out = client.query(f"collection://{DS}", filter=flt, filter_properties=["title"],
                           page_size=10, max_pages=2)
        self.assertEqual(len(opener.requests), 2)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["next_cursor"], "c1")
        first = opener.requests[0]
        self.assertEqual(first.get_method(), "POST")
        self.assertTrue(first.full_url.startswith(f"https://api.notion.com/v1/data_sources/{DS}/query"))
        self.assertIn("filter_properties=title", first.full_url)
        body = json.loads(first.data)
        self.assertEqual(body["filter"], flt)
        self.assertEqual(body["page_size"], 10)
        self.assertNotIn("start_cursor", body)
        self.assertEqual(json.loads(opener.requests[1].data)["start_cursor"], "c0")
        self.assertEqual(first.headers["Notion-version"], "2025-09-03")

    def test_complete_read_is_not_marked_truncated(self):
        client, _, _ = make_client([{"results": [{"id": "a"}], "has_more": False, "next_cursor": None}])
        out = client.query(DS, max_pages=5)
        self.assertFalse(out["truncated"])
        self.assertEqual(out["pages_fetched"], 1)

    def test_rate_limiter_spaces_requests_to_three_per_second(self):
        pages = [{"results": [], "has_more": True, "next_cursor": "c"}] * 3
        client, _, clock = make_client(pages)
        client.query(DS, max_pages=3)
        self.assertEqual(len(clock.sleeps), 2)
        for s in clock.sleeps:
            self.assertAlmostEqual(s, 1 / 3, places=6)

    def test_429_honours_retry_after_then_succeeds(self):
        client, opener, clock = make_client([
            http_error(429, retry_after=2),
            {"results": [{"id": "x"}], "has_more": False},
        ])
        out = client.query(DS)
        self.assertEqual(len(out["results"]), 1)
        self.assertIn(2.0, clock.sleeps)
        self.assertEqual(len(opener.requests), 2)

    def test_retries_are_bounded_and_error_is_token_free(self):
        client, opener, _ = make_client([http_error(429)] * 4)
        with self.assertRaises(NotionAPIError) as ctx:
            client.query(DS)
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(len(opener.requests), 4)
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_non_retryable_error_raises_immediately(self):
        client, opener, _ = make_client([http_error(404, code="object_not_found")])
        with self.assertRaises(NotionAPIError) as ctx:
            client.retrieve_page(DS)
        self.assertEqual(ctx.exception.code, "object_not_found")
        self.assertEqual(len(opener.requests), 1)

    def test_write_endpoints_are_rejected(self):
        client, opener, _ = make_client([])
        with self.assertRaises(NotionConfigurationError):
            client._request("PATCH", f"/v1/pages/{DS}", {"properties": {}})
        with self.assertRaises(NotionConfigurationError):
            client._request("POST", "/v1/pages", {})
        self.assertEqual(opener.requests, [])

    def test_resolve_database_to_data_source(self):
        client, _, _ = make_client([{"object": "database", "data_sources": [{"id": DS, "name": "R"}]}])
        self.assertEqual(client.resolve_data_source_ids(DB), [DS])


class SimplifyAndCliTests(unittest.TestCase):
    PAGE = {
        "id": "p1", "url": "https://www.notion.so/p1", "last_edited_time": "2026-11-20T00:00:00.000Z",
        "properties": {
            "Position": {"type": "title", "title": [{"plain_text": "연구원"}]},
            "State": {"type": "status", "status": {"name": "ACTIVE"}},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "a"}, {"name": "b"}]},
            "Deadline": {"type": "date", "date": {"start": "2026-11-30", "end": None}},
            "Score": {"type": "number", "number": 72},
        },
    }

    def test_simplify_page(self):
        row = simplify_page(self.PAGE)
        self.assertEqual(row["properties"]["Position"], "연구원")
        self.assertEqual(row["properties"]["State"], "ACTIVE")
        self.assertEqual(row["properties"]["Tags"], ["a", "b"])
        self.assertEqual(row["properties"]["Deadline"]["start"], "2026-11-30")
        self.assertEqual(row["properties"]["Score"], 72)

    def test_cli_query_with_where_and_date_range(self):
        client, opener, _ = make_client([{"results": [self.PAGE], "has_more": False}])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["query", "--data-source", DS,
                         "--where", 'State|status|equals|"ACTIVE"',
                         "--date-prop", "Deadline", "--since", "2026-11-20",
                         "--sort", "Deadline:ascending", "--page-size", "20"], client=client)
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["count"], 1)
        self.assertFalse(out["truncated"])
        body = json.loads(opener.requests[0].data)
        self.assertEqual(body["filter"]["and"][0], {"property": "State", "status": {"equals": "ACTIVE"}})
        self.assertEqual(body["filter"]["and"][1], {"property": "Deadline", "date": {"on_or_after": "2026-11-20"}})
        self.assertEqual(body["sorts"], [{"property": "Deadline", "direction": "ascending"}])

    def test_cli_without_token_exits_2(self):
        with patch.dict(os.environ, {"NOTION_TOKEN": ""}, clear=False):
            with redirect_stdout(io.StringIO()):
                with patch("sys.stderr", new=io.StringIO()):
                    self.assertEqual(main(["query", "--data-source", DS]), 2)


if __name__ == "__main__":
    unittest.main()
