"""Tests for the policy-bounded public search adapter and orchestration contract."""
import os
import unittest
from unittest.mock import patch

from adapters.public_search import (
    AdapterConfigurationError,
    PLATFORM_DOMAINS,
    PublicSearchAdapter,
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


if __name__ == "__main__":
    unittest.main()
