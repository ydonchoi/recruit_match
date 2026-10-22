"""Tests for requirement-centered job matching without applicant profiles."""
import unittest

from job_matching_model import (
    CriterionDecision,
    JobRequirement,
    ModelValidationError,
    SourceDocument,
    build_evaluation_run,
    retrieve_evidence_on_demand,
)


class JobMatchingModelTests(unittest.TestCase):
    def setUp(self):
        self.requirement = JobRequirement(
            requirement_id="REQ-SQL",
            description="SQL data analysis",
            requirement_type="TECHNICAL",
            weight=1.0,
            keywords=("SQL", "data analysis"),
            target_level=3,
        )
        self.document = SourceDocument(
            document_id="DOC-1",
            text="I worked as a coordinator. I used SQL for data analysis and reporting.",
            source_url="https://example.org/material",
            source_type="resume",
            observed_at="2026-10-22T10:00:00Z",
        )

    def test_retrieves_relevant_source_excerpt_on_demand(self):
        snippets = retrieve_evidence_on_demand(self.requirement, [self.document])
        self.assertTrue(snippets)
        self.assertTrue(any("SQL" in item.excerpt for item in snippets))
        self.assertEqual(snippets[0].document_id, "DOC-1")
        self.assertGreaterEqual(snippets[0].end_offset, snippets[0].start_offset)

    def test_no_match_is_not_a_zero_score(self):
        unrelated = SourceDocument("DOC-2", "Managed office calendars.", "https://example.org/other")
        self.assertEqual(retrieve_evidence_on_demand(self.requirement, [unrelated]), [])
        result = build_evaluation_run(
            evaluation_id="EVAL-1", job_id="JOB-1",
            requirements=[self.requirement], documents=[unrelated],
            decisions=[CriterionDecision("REQ-SQL", 0, "ASSESSED", ("not-found",))],
        )
        self.assertIsNone(result["fit_score"])
        self.assertEqual(result["evaluation_status"], "UNASSESSED")
        self.assertEqual(result["criterion_results"][0]["status"], "UNASSESSED")

    def test_evaluation_stores_run_level_decisions_and_evidence(self):
        snippets = retrieve_evidence_on_demand(self.requirement, [self.document])
        result = build_evaluation_run(
            evaluation_id="EVAL-2", job_id="JOB-1",
            requirements=[self.requirement], documents=[self.document],
            decisions=[CriterionDecision(
                "REQ-SQL", 4, "ASSESSED", (snippets[0].evidence_id,),
                rationale="Specific SQL use is described.",
            )],
            eligibility_status="HOLD",
            evaluated_at="2026-10-22T10:05:00Z",
        )
        self.assertEqual(result["evaluation_status"], "ASSESSED")
        self.assertEqual(result["fit_score"], 80.0)
        self.assertEqual(result["evidence_coverage"], 1.0)
        self.assertEqual(result["eligibility"]["status"], "HOLD")
        self.assertIn("evidence_records", result)
        self.assertNotIn("applicant_profile", result)
        self.assertEqual(result["criterion_results"][0]["evidence_refs"], [snippets[0].evidence_id])

    def test_missing_requirement_decision_makes_run_provisional(self):
        result = build_evaluation_run(
            evaluation_id="EVAL-3", job_id="JOB-1",
            requirements=[self.requirement], documents=[self.document], decisions=[],
        )
        self.assertEqual(result["evaluation_status"], "UNASSESSED")
        self.assertIsNone(result["fit_score"])
        self.assertEqual(result["unresolved_requirements"], ["REQ-SQL"])

    def test_duplicate_requirement_ids_are_rejected(self):
        with self.assertRaises(ModelValidationError):
            build_evaluation_run(
                evaluation_id="EVAL-4", job_id="JOB-1",
                requirements=[self.requirement, self.requirement],
                documents=[self.document], decisions=[],
            )


if __name__ == "__main__":
    unittest.main()
