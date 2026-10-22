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


    def test_requirement_centered_matching_bridge_keeps_profile_unstructured(self):
        from analysis_pipeline import evaluate_job_matching_payload
        payload = {
            "evaluation_id": "eval-bridge",
            "job_id": "job-bridge",
            "eligibility_status": "HOLD",
            "requirements": [{
                "requirement_id": "REQ-1",
                "description": "SQL data analysis",
                "requirement_type": "TECHNICAL",
                "weight": 1.0,
                "keywords": ["SQL", "analysis"],
            }],
            "documents": [{
                "document_id": "DOC-1",
                "text": "Used SQL for analysis and reporting.",
                "source_url": "https://example.org/source",
            }],
            "decisions": [{
                "requirement_id": "REQ-1",
                "score": 4,
                "status": "ASSESSED",
                "evidence_refs": ["DOC-1:0-37"],
                "rationale": "Specific evidence is present.",
            }],
        }
        result = evaluate_job_matching_payload(payload)
        self.assertEqual(result["evaluation_id"], "eval-bridge")
        self.assertEqual(result["eligibility"]["status"], "HOLD")
        self.assertNotIn("applicant_profile", result)
        self.assertEqual(result["evaluation_status"], "ASSESSED")
        self.assertEqual(result["fit_score"], 80.0)

    def test_requirement_centered_bridge_rejects_unknown_requirement_type(self):
        from analysis_pipeline import evaluate_job_matching_payload
        with self.assertRaises(ValueError):
            evaluate_job_matching_payload({
                "evaluation_id": "eval-invalid",
                "job_id": "job-invalid",
                "requirements": [{
                    "requirement_id": "REQ-1",
                    "description": "Skill",
                    "requirement_type": "UNKNOWN",
                }],
                "documents": [],
                "decisions": [],
            })


if __name__ == "__main__":
    unittest.main()
