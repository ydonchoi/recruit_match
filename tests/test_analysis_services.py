"""Tests for the external analysis-service connector contract."""
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import URLError

import analysis_services


class AnalysisServiceTests(unittest.TestCase):
    def test_missing_configuration_is_blocked_without_network(self):
        keys = [
            "RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS",
        ]
        with patch.dict(os.environ, {key: "" for key in keys}, clear=False):
            result = analysis_services.readiness()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("reason", result)

    def test_rejects_non_https_or_unallowlisted_host(self):
        with patch.dict(os.environ, {
            "RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL": "http://localhost:8000",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN": "test-only",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS": "localhost",
        }, clear=False):
            with self.assertRaises(analysis_services.AnalysisServiceConfigurationError):
                analysis_services.readiness()

    def test_configured_status_does_not_claim_live_test(self):
        with patch.dict(os.environ, {
            "RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL": "https://analysis.example",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN": "test-only",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS": "analysis.example",
        }, clear=False):
            result = analysis_services.readiness()
        self.assertEqual(result["status"], "CONFIGURED_NOT_LIVE_TESTED")

    def test_response_schema_rejects_invalid_evidence_fields(self):
        payload = {"evidence_refs": "not-a-list"}
        with patch.dict(os.environ, {
            "RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL": "https://analysis.example",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN": "test-only",
            "RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS": "analysis.example",
        }, clear=False), patch.object(analysis_services, "urlopen") as mocked:
            mocked.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
            mocked.return_value.__enter__.return_value.status = 200
            with self.assertRaises(analysis_services.AnalysisServiceRequestError):
                analysis_services.opportunity_state_resolution({"official_url": "https://example.org/job"})


if __name__ == "__main__":
    unittest.main()
