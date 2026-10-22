"""Regression tests for the ported policy-bounded HTML discovery adapter."""
import os
import tempfile
import unittest
from unittest.mock import patch

from adapters.public_html_crawl import (
    AnchorParser, CrawlConfig, CrawlConfigurationError, CompositeAdapter,
    PublicHTMLCrawlAdapter, configs_from_environment,
)


class PublicHTMLCrawlTests(unittest.TestCase):
    def test_anchor_parser_extracts_links(self):
        parser = AnchorParser()
        parser.feed('<a href="/jobs/1">교육행정 연구원 채용</a>')
        self.assertEqual(parser.links, [('/jobs/1', '교육행정 연구원 채용')])

    def test_config_requires_explicit_json_and_review(self):
        with patch.dict(os.environ, {"RECRUIT_MATCH_CRAWL_CONFIG_JSON": ""}, clear=False):
            self.assertEqual(configs_from_environment(), {})
        payload = '[{"platform":"KEDI","seed_urls":["https://kedi.re.kr/jobs"],"allowed_hosts":["kedi.re.kr"],"terms_reviewed":false}]'
        with patch.dict(os.environ, {"RECRUIT_MATCH_CRAWL_CONFIG_JSON": payload}, clear=False):
            self.assertEqual(configs_from_environment(), {})

    def test_config_rejects_unknown_platform_and_untrusted_seed(self):
        payload = '[{"platform":"not-a-platform","seed_urls":["https://example.org/jobs"],"allowed_hosts":["example.org"],"terms_reviewed":true}]'
        with patch.dict(os.environ, {"RECRUIT_MATCH_CRAWL_CONFIG_JSON": payload}, clear=False):
            with self.assertRaises(CrawlConfigurationError):
                configs_from_environment()
        payload = '[{"platform":"KEDI","seed_urls":["https://evil.example/jobs"],"allowed_hosts":["kedi.re.kr"],"terms_reviewed":true}]'
        with patch.dict(os.environ, {"RECRUIT_MATCH_CRAWL_CONFIG_JSON": payload}, clear=False):
            with self.assertRaises(PermissionError):
                configs_from_environment()

    def test_search_is_discovery_only_and_keeps_content_hash_provenance(self):
        config = CrawlConfig("KEDI", ("https://kedi.re.kr/jobs",), ("kedi.re.kr",), True, max_links_per_seed=10)
        adapter = PublicHTMLCrawlAdapter(config)
        listing = b'<a href="/jobs/1">교육행정 연구원 채용</a><a href="https://outside.example/job">외부</a>'
        adapter._fetch = lambda url: ("https://kedi.re.kr/jobs", "text/html", listing)
        with tempfile.TemporaryDirectory() as tmp, patch("adapters.public_html_crawl.ARTIFACT_DIR", __import__("pathlib").Path(tmp)):
            rows = adapter.search({"query": "교육행정 채용"})
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["official_url"], "https://kedi.re.kr/jobs/1")
            self.assertEqual(row["application_status"], "unknown")
            self.assertEqual(row["eligibility_status"], "unverified")
            self.assertFalse(row["authoritative_source"])
            self.assertTrue(row["source_content_sha256"])
            self.assertTrue(row["provenance_refs"])

    def test_composite_preserves_partial_source_failure(self):
        class Good:
            def search(self, context):
                return [{"official_url": "https://kedi.re.kr/job"}]
        class Bad:
            def search(self, context):
                raise RuntimeError("provider down")
        rows = CompositeAdapter("KEDI", (Good(), Bad())).search({"query": "job"})
        self.assertEqual(len(rows), 1)
        self.assertIn("RuntimeError", rows[0]["source_discovery_errors"][0])


if __name__ == "__main__":
    unittest.main()
