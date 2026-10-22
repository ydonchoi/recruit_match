"""Offline readiness checks for the empirical integration workflow.

These tests must not make network requests or claim live-source coverage.
"""
import os
import unittest
from unittest.mock import patch

import run_pipeline
from adapters.public_search import AdapterConfigurationError, PublicSearchAdapter


class EmpiricalReadinessTests(unittest.TestCase):
    def test_all_baseline_platforms_have_discovery_adapter_entries(self):
        adapters = run_pipeline.load_adapters()
        missing = sorted(set(run_pipeline.BASELINE_PLATFORMS) - set(adapters))
        self.assertEqual(missing, [], f"Baseline adapters missing: {missing}")

    def test_search_without_credentials_is_blocked_before_network(self):
        with patch.dict(os.environ, {
            "RECRUIT_MATCH_SEARCH_ENDPOINT": "",
            "RECRUIT_MATCH_SEARCH_API_KEY": "",
            "RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS": "",
        }, clear=False), patch("adapters.public_search.urlopen") as mocked_urlopen:
            adapter = PublicSearchAdapter("TEST", ("example.org",))
            with self.assertRaises(AdapterConfigurationError):
                adapter.search({"query": "offline test"})
            mocked_urlopen.assert_not_called()

    def test_analysis_readiness_does_not_claim_live_test_without_configuration(self):
        import analysis_services

        with patch.dict(os.environ, {
            "RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL": "",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN": "",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS": "",
        }, clear=False):
            result = analysis_services.readiness()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotIn("token", result)
        self.assertNotIn("api_key", result)


if __name__ == "__main__":
    unittest.main()
