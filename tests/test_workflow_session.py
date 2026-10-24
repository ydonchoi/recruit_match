"""Tests for privacy-bounded user selection and in-memory workflow state."""
import unittest

from job_matching_model import JobRequirement, SourceDocument, retrieve_evidence_on_demand
from run_pipeline import sanitize_run_record, sanitize_search_text
from workflow_session import (
    APPLICATION_STAGES, ApplicationCase, WorkflowInputError,
    evaluate_single_posting, select_postings,
)


class WorkflowSessionTests(unittest.TestCase):
    def test_multi_select_returns_only_requested_postings_in_ledger_order(self):
        postings = [
            {"posting_id": "p1"}, {"posting_id": "p2"}, {"posting_id": "p3"},
        ]
        self.assertEqual(select_postings(postings, ["p3", "p1"]), [postings[0], postings[2]])

    def test_multi_select_rejects_unknown_or_empty_selection(self):
        with self.assertRaises(WorkflowInputError):
            select_postings([{"posting_id": "p1"}], ["p2"])
        with self.assertRaises(WorkflowInputError):
            select_postings([{"posting_id": "p1"}], [])

    def test_candidate_evaluation_is_returned_in_memory_with_explicit_threshold(self):
        posting = {"posting_id": "p1", "official_url": "https://jobs.example.invalid/1"}
        requirement = JobRequirement(
            requirement_id="r1", description="SQL analysis", requirement_type="TECHNICAL",
            mandatory=True, weight=1.0, keywords=("SQL", "analysis"),
        )
        document = SourceDocument(
            document_id="session-candidate-material",
            text="Used SQL for monthly analysis and reporting.",
        )
        snippet = retrieve_evidence_on_demand(requirement, [document])[0]
        result = evaluate_single_posting(
            posting=posting, requirements=[requirement],
            candidate_text=document.text, eligibility_status="PASS",
            criterion_decisions={"r1": {
                "score": 4, "status": "ASSESSED",
                "evidence_refs": [snippet.evidence_id], "rationale": "Evidence reviewed.",
            }},
            min_fit_score=75,
        )
        self.assertEqual(result["fit_score"], 80.0)
        self.assertEqual(result["recommendation"], "RECOMMENDED_FOR_USER_REVIEW")
        self.assertEqual(result["recommendation_policy"]["status"], "USER_CONFIGURED_UNCALIBRATED_RULE")
        self.assertIn("Used SQL", result["evidence_records"][0]["excerpt"])

    def test_candidate_evaluation_rejects_cross_requirement_evidence(self):
        req1 = JobRequirement("r1", "SQL", "TECHNICAL", weight=1.0, keywords=("SQL",))
        req2 = JobRequirement("r2", "Python", "TECHNICAL", weight=1.0, keywords=("Python",))
        doc = SourceDocument("session-candidate-material", "Used SQL for reporting.")
        sql_ref = retrieve_evidence_on_demand(req1, [doc])[0].evidence_id
        with self.assertRaises(WorkflowInputError):
            evaluate_single_posting(
                posting={"posting_id": "p1"}, requirements=[req1, req2],
                candidate_text=doc.text, eligibility_status="PASS",
                criterion_decisions={"r2": {
                    "score": 4, "status": "ASSESSED", "evidence_refs": [sql_ref],
                }},
            )

    def test_mandatory_requirement_below_three_blocks_recommendation(self):
        requirement = JobRequirement(
            requirement_id="r1", description="SQL", requirement_type="TECHNICAL",
            mandatory=True, weight=1.0, keywords=("SQL",),
        )
        doc = SourceDocument("session-candidate-material", "Used SQL for reporting.")
        evidence = retrieve_evidence_on_demand(requirement, [doc])[0]
        result = evaluate_single_posting(
            posting={"posting_id": "p1"}, requirements=[requirement],
            candidate_text=doc.text, eligibility_status="PASS",
            criterion_decisions={"r1": {
                "score": 2, "status": "ASSESSED", "evidence_refs": [evidence.evidence_id],
            }},
            min_fit_score=50,
        )
        self.assertEqual(result["recommendation"], "NOT_RECOMMENDED_MANDATORY_REQUIREMENT")

    def test_application_case_requires_explicit_sequential_confirmation(self):
        case = ApplicationCase("public-posting-1")
        with self.assertRaises(WorkflowInputError):
            case.advance(APPLICATION_STAGES[1], user_confirmed=False)
        with self.assertRaises(WorkflowInputError):
            case.advance(APPLICATION_STAGES[2], user_confirmed=True)
        case.advance(APPLICATION_STAGES[1], user_confirmed=True, note="Reviewed")
        self.assertEqual(case.status, "DOCUMENTS_REVIEW")
        self.assertEqual(len(case.events), 2)

    def test_run_log_sanitizer_removes_user_text_and_legacy_query_records(self):
        safe = sanitize_run_record({
            "run_id": "r1", "status": "completed", "query_axes": ["private skill"],
            "queries_executed": ["person@example.invalid job"],
            "errors_or_limitations": ["old error with person@example.invalid"],
            "orchestration_summary": {
                "completed": 1,
                "execution_records": [{"query": "person@example.invalid", "query_id": "hashed"}],
            },
        }, legacy=True)
        serialized = str(safe)
        self.assertNotIn("person@example.invalid", serialized)
        self.assertNotIn("private skill", serialized)
        self.assertEqual(safe["errors_or_limitations"], ["LEGACY_DETAILS_REDACTED"])
        self.assertEqual(safe["orchestration_summary"]["execution_records"], [])

    def test_search_text_removes_common_direct_identifiers(self):
        query = "연구지원 jane@example.invalid 010-1234-5678"
        safe = sanitize_search_text(query)
        self.assertIn("연구지원", safe)
        self.assertNotIn("jane@example.invalid", safe)
        self.assertNotIn("010-1234-5678", safe)


if __name__ == "__main__":
    unittest.main()
