"""Regression tests for the independent canonical analysis pipeline."""
import unittest
from analysis_pipeline import run_analysis_pipeline, CANONICAL_STAGE_ORDER


class AnalysisPipelineTests(unittest.TestCase):
    def test_canonical_stage_order_is_preserved(self):
        result = run_analysis_pipeline(run_id="test-order", postings=[], require_all_services=False)
        self.assertEqual(tuple(stage.name for stage in result.stages), CANONICAL_STAGE_ORDER)

    def test_missing_required_services_fail_closed(self):
        result = run_analysis_pipeline(
            run_id="test-blocked",
            postings=[{"posting_id": "p1", "institution": "기관", "title": "연구원",
                       "official_url": "https://example.invalid/job"}],
            services={},
            require_all_services=True,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertTrue(any("MISSING_REQUIRED_SERVICE" in error for error in result.errors))
        self.assertEqual(result.records[0]["writer_gate"], "HOLD")

    def test_unknown_eligibility_never_passes_writer_gate(self):
        result = run_analysis_pipeline(
            run_id="test-eligibility",
            postings=[{"posting_id": "p1", "institution": "기관", "title": "연구원",
                       "official_url": "https://example.invalid/job",
                       "application_status": "open", "deadline_at": "2026-12-31",
                       "authoritative_source": True, "decision_source_verified": True,
                       "evidence_refs": ["official-page"], "provenance_refs": ["sha256:x"],
                       "candidate_recruitment_evidence_separated": True,
                       "eligibility_status": "unverified"}],
            services={"opportunity_state_resolution": lambda row: {},
                      "assessment_resolution": lambda row: {},
                      "revalidation": lambda row: {"status": "UNVERIFIED"}},
            require_all_services=True,
        )
        self.assertEqual(result.records[0]["writer_gate"], "HOLD")
        self.assertEqual(result.records[0]["eligibility_gate"], "HOLD")


if __name__ == "__main__":
    unittest.main()
