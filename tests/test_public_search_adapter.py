"""Tests for the policy-bounded public search adapter and orchestration contract."""
import os
import unittest
from unittest.mock import patch

from adapters.public_search import (
    AdapterConfigurationError,
    PLATFORM_DOMAINS,
    PublicSearchAdapter,
    SearchConfig,
    _config,
)
from search_orchestrator import execute_search_plan, summarize_executions


class PublicSearchAdapterTests(unittest.TestCase):
    def test_adapter_registry_covers_all_baseline_platforms(self):
        expected = {
            "JOB-ALIO", "NKIS", "나라일터", "고용24", "사람인", "잡코리아",
            "클린아이 잡플러스", "대학 공식 채용 페이지", "하이브레인넷",
            "연구기관 공식 채용 페이지", "KEDI", "KICE",
        }
        self.assertEqual(set(PLATFORM_DOMAINS), expected)

    def test_missing_endpoint_fails_closed(self):
        env = {
            "RECRUIT_MATCH_SEARCH_ENDPOINT": "",
            "RECRUIT_MATCH_SEARCH_API_KEY": "dummy",
            "RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS": "search.example",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(AdapterConfigurationError):
                _config()

    def test_endpoint_must_be_allowlisted_https(self):
        env = {
            "RECRUIT_MATCH_SEARCH_ENDPOINT": "https://not-allowed.example/search",
            "RECRUIT_MATCH_SEARCH_API_KEY": "dummy",
            "RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS": "search.example",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(AdapterConfigurationError):
                _config()

    def test_orchestrator_records_provider_failure_without_fabricating_hits(self):
        class BrokenAdapter:
            def search(self, context):
                raise RuntimeError("provider unavailable")

        rows = execute_search_plan(
            run_id="test-run", queries=["교육행정 채용"],
            platforms=["JOB-ALIO"], adapters={"JOB-ALIO": BrokenAdapter()},
            context={},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].run.status, "FAILED")
        self.assertEqual(rows[0].hits, ())
        summary = summarize_executions(rows)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["raw_results"], 0)
        self.assertNotIn("query", summary["execution_records"][0])

    def test_orchestrator_batches_provider_calls_but_keeps_platform_run_rows(self):
        class BatchAdapter:
            def __init__(self, platform):
                self.platform = platform

            def search_batch(self, context, adapters):
                return {
                    platform: [{
                        "institution": platform, "title": "Research role",
                        "official_url": f"https://{platform}.example/job",
                    }]
                    for platform in adapters
                }

            def search(self, context):
                raise AssertionError("individual fallback should not run")

        adapters = {name: BatchAdapter(name) for name in ("A", "B")}
        rows = execute_search_plan(
            run_id="run", queries=["private query"], platforms=["A", "B"],
            adapters=adapters, context={},
        )
        self.assertEqual([row.run.status for row in rows], ["COMPLETED", "COMPLETED"])
        self.assertTrue(all(row.run.execution_mode == "grouped" for row in rows))
        summary = summarize_executions(rows)
        self.assertEqual(summary["queries_platform_pairs"], 2)
        self.assertNotIn("private query", str(summary))
        self.assertTrue(all("query" not in row for row in summary["execution_records"]))

    def test_grouped_search_routes_results_to_every_platform_with_two_provider_calls(self):
        adapters = {
            "KEDI": PublicSearchAdapter("KEDI", ("kedi.re.kr",)),
            "KICE": PublicSearchAdapter("KICE", ("kice.re.kr",)),
            "대학 공식 채용 페이지": PublicSearchAdapter("대학 공식 채용 페이지", ()),
            "연구기관 공식 채용 페이지": PublicSearchAdapter("연구기관 공식 채용 페이지", ()),
        }
        first = adapters["KEDI"]
        calls = []

        def fake_fetch(query, config):
            calls.append(query)
            if "site:" in query:
                return [
                    {"url": "https://www.kedi.re.kr/job/1", "name": "KEDI job", "siteName": "KEDI"},
                    {"url": "https://kice.re.kr/job/2", "name": "KICE job", "siteName": "KICE"},
                    {"url": "https://outside.example/job/3", "name": "Wrong channel", "siteName": "outside"},
                ]
            return [
                {"url": "https://unmapped.example/job/4", "name": "Other public job", "siteName": "Public agency"},
                {"url": "https://kedi.re.kr/job/1", "name": "Mapped site", "siteName": "KEDI"},
            ]

        first._fetch_pages = fake_fetch
        with patch("adapters.public_search._config", return_value=SearchConfig("https://s.example", "key")):
            routed = first.search_batch({"query": "public research hiring"}, adapters)
        self.assertEqual(len(calls), 2)
        self.assertEqual([row["official_url"] for row in routed["KEDI"]], ["https://www.kedi.re.kr/job/1"])
        self.assertEqual([row["official_url"] for row in routed["KICE"]], ["https://kice.re.kr/job/2"])
        self.assertEqual([row["official_url"] for row in routed["대학 공식 채용 페이지"]], ["https://unmapped.example/job/4"])
        self.assertEqual([row["official_url"] for row in routed["연구기관 공식 채용 페이지"]], ["https://unmapped.example/job/4"])


if __name__ == "__main__":
    unittest.main()
