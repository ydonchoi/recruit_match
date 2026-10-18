import unittest

from recruit_match.platform_registry import (
    INTEGRATION_STATUSES,
    PLATFORM_REGISTRY,
    PlatformSource,
    get_platform,
    list_platforms,
    select_platforms,
)


class PlatformRegistryTests(unittest.TestCase):
    def test_platform_ids_are_unique_and_catalog_is_not_empty(self):
        ids = [source.platform_id for source in PLATFORM_REGISTRY]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_catalog_entries_have_valid_urls_and_policy_metadata(self):
        for source in PLATFORM_REGISTRY:
            with self.subTest(platform_id=source.platform_id):
                self.assertIn(source.integration_status, INTEGRATION_STATUSES)
                self.assertIn(source.priority, (1, 2, 3))
                self.assertTrue(source.homepage_url or source.discovery_url)
                if source.integration_status == "api_documented":
                    self.assertEqual(source.access_mode, "api")
                    self.assertTrue(source.api_docs_url)

    def test_api_candidates_are_explicit_and_not_implicitly_enabled(self):
        api_sources = list_platforms(integration_status="api_documented")
        self.assertEqual(
            {source.platform_id for source in api_sources},
            {"saramin", "work24", "jobaba"},
        )
        self.assertTrue(all(source.api_docs_url for source in api_sources))

    def test_public_institution_filter_includes_central_and_local_sources(self):
        sources = list_platforms(categories=("public_institution",))
        ids = {source.platform_id for source in sources}
        self.assertIn("alio_job", ids)
        self.assertIn("cleaneye_jobplus", ids)

    def test_university_and_research_sources_are_available(self):
        university = select_platforms(("university_faculty", "university_staff"))
        ids = {source.platform_id for source in university}
        self.assertIn("hibrain", ids)
        self.assertIn("university_official_boards", ids)
        self.assertTrue(
            get_platform("university_official_boards").discovery_url
        )

    def test_category_selection_is_independent_of_search_matrix_shape(self):
        sources = select_platforms(("developer", "research"))
        ids = {source.platform_id for source in sources}
        self.assertIn("jumpit", ids)
        self.assertIn("hibrain", ids)
        self.assertIn("rndjob", ids)
        self.assertNotIn("alio_job", ids)

    def test_unknown_platform_and_invalid_filters_fail_explicitly(self):
        with self.assertRaisesRegex(KeyError, "PLATFORM_NOT_FOUND"):
            get_platform("not-a-platform")
        with self.assertRaisesRegex(ValueError, "PLATFORM_FILTER_CATEGORY_INVALID"):
            list_platforms(categories=("not-a-category",))
        with self.assertRaisesRegex(ValueError, "PLATFORM_FILTER_STATUS_INVALID"):
            list_platforms(integration_status="enabled")

    def test_invalid_platform_metadata_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "DOCUMENTED_API_REQUIRES_API_MODE_AND_DOCS"):
            PlatformSource(
                "broken_api", "Broken", ("general",), "https://example.org/",
                "web", "api_documented", 1,
            )
        with self.assertRaisesRegex(ValueError, "PLATFORM_URL_OR_DISCOVERY_URL_REQUIRED"):
            PlatformSource(
                "missing_url", "Missing", ("general",), None,
                "web", "candidate_unverified", 2,
            )


if __name__ == "__main__":
    unittest.main()
