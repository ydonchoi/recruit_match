import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from recruit_match.application import run_analysis
from recruit_match.pipeline import StageStatus
from recruit_match.runner import StageExecution
from recruit_match.search_execution import SearchCallStatus
from recruit_match.search_stage import (
    SearchProviderHit,
    build_search_discovery_handler,
    build_search_handlers,
    build_search_plan_handler,
)


class SearchStageAdapterTests(unittest.TestCase):
    def setUp(self):
        self.combinations = (
            SimpleNamespace(combination_id="matrix-A", query="university admin"),
            SimpleNamespace(combination_id="matrix-B", query="research support"),
        )

    def fixed_clock(self):
        return lambda: datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    def test_search_plan_handler_exposes_stable_combinations(self):
        handler = build_search_plan_handler(
            lambda context: self.combinations,
            max_planned_combinations=5,
        )
        result = handler({})
        self.assertEqual(result.status, StageStatus.SUCCESS)
        self.assertEqual(result.output["search_plan_count"], 2)
        self.assertEqual(
            result.output["search_plan_combination_ids"],
            ("matrix-A", "matrix-B"),
        )

    def test_search_plan_blocks_oversized_matrix_without_truncating(self):
        handler = build_search_plan_handler(
            lambda context: self.combinations,
            max_planned_combinations=1,
        )
        result = handler({})
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "SEARCH_PLAN_EXCEEDS_MAX_COMBINATIONS")
        self.assertEqual(result.output["search_plan_count"], 2)

    def test_search_plan_blocks_empty_matrix(self):
        result = build_search_plan_handler(
            lambda context: (), max_planned_combinations=3
        )({})
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "SEARCH_PLAN_EMPTY")

    def test_search_plan_rejects_duplicate_combination_ids(self):
        duplicate = (
            SimpleNamespace(combination_id="same", query="query one"),
            SimpleNamespace(combination_id="same", query="query two"),
        )
        result = build_search_plan_handler(
            lambda context: duplicate, max_planned_combinations=3
        )({})
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "SEARCH_PLAN_INVALID")

    def test_discovery_records_provider_results_and_observation_times(self):
        calls = []
        handler = build_search_discovery_handler(
            run_id="run-1",
            provider_id="approved-test-provider",
            search_callable=lambda query: calls.append(query) or (
                SearchProviderHit("result-1", "Recruitment notice", "https://example.org/jobs/1"),
            ),
            max_calls=2,
            clock=self.fixed_clock(),
        )
        result = handler({"search_combinations": self.combinations})
        self.assertEqual(result.status, StageStatus.SUCCESS)
        self.assertEqual(calls, ["university admin", "research support"])
        report = result.output["search_execution_report"]
        self.assertEqual(report.attempted_call_count, 2)
        self.assertEqual(report.successful_call_count, 2)
        self.assertEqual(len(result.output["discovered_search_results"]), 2)
        first = result.output["discovered_search_results"][0]
        self.assertEqual(first.provider_id, "approved-test-provider")
        self.assertEqual(first.combination_id, "matrix-A")
        self.assertEqual(first.observed_at, "2026-10-19T12:00:00+00:00")
        self.assertTrue(first.query_sha256)
        self.assertEqual(len(result.evidence_refs), 2)

    def test_discovery_blocks_partial_run_when_call_budget_is_exhausted(self):
        calls = []
        handler = build_search_discovery_handler(
            run_id="run-2",
            provider_id="approved-test-provider",
            search_callable=lambda query: calls.append(query) or (),
            max_calls=1,
            clock=self.fixed_clock(),
        )
        result = handler({"search_combinations": self.combinations})
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "SEARCH_PLAN_NOT_FULLY_EXECUTED")
        self.assertEqual(calls, ["university admin"])
        report = result.output["search_execution_report"]
        self.assertEqual(report.attempted_call_count, 1)
        self.assertEqual(report.skipped_query_count, 1)
        self.assertFalse(result.output["discovery_complete"])
        self.assertEqual(
            result.output["search_invocation_receipts"][1].status,
            SearchCallStatus.SKIPPED_BUDGET,
        )

    def test_discovery_fails_if_every_provider_call_fails(self):
        def provider(query):
            raise RuntimeError("private error")

        result = build_search_discovery_handler(
            run_id="run-3",
            provider_id="test-provider",
            search_callable=provider,
            max_calls=2,
            clock=self.fixed_clock(),
        )({"search_combinations": self.combinations})
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.reason, "NO_SEARCH_CALL_SUCCEEDED")
        self.assertNotIn("private error", repr(result.output))
        self.assertEqual(
            result.output["search_execution_report"].failed_call_count, 2
        )

    def test_malformed_provider_result_fails_closed(self):
        result = build_search_discovery_handler(
            run_id="run-4",
            provider_id="test-provider",
            search_callable=lambda query: ({"title": "not normalized"},),
            max_calls=1,
            clock=self.fixed_clock(),
        )({"search_combinations": self.combinations[:1]})
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(
            result.output["search_execution_report"].failed_call_count, 1
        )

    def test_invalid_result_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SEARCH_RESULT_URL_INVALID"):
            SearchProviderHit("id", "title", "file:///etc/passwd")

    def test_credential_bearing_result_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SEARCH_RESULT_URL_CREDENTIALS_FORBIDDEN"):
            SearchProviderHit("id", "title", "https://user:pass@example.org/job")

    def test_missing_search_combinations_blocks_discovery(self):
        result = build_search_discovery_handler(
            run_id="run-5",
            provider_id="test-provider",
            search_callable=lambda query: (),
            max_calls=1,
            clock=self.fixed_clock(),
        )({})
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "SEARCH_COMBINATIONS_MISSING")

    def test_search_handlers_connect_to_run_analysis_discovery_stage(self):
        calls = []
        handlers = build_search_handlers(
            run_id="integrated-synthetic",
            planner=lambda context: self.combinations,
            search_callable=lambda query: calls.append(query) or (
                SearchProviderHit("id-" + str(len(calls)), "Notice", "https://example.org/job"),
            ),
            provider_id="synthetic-provider",
            max_planned_combinations=4,
            max_calls=2,
            clock=self.fixed_clock(),
        )
        handlers.update({
            "request_scope": lambda context: StageExecution(
                StageStatus.SUCCESS, {"request_scope_state": "VALID"}
            ),
            "candidate_context": lambda context: StageExecution(
                StageStatus.SUCCESS, {"candidate_context_ref": "synthetic:candidate-context"},
                evidence_refs=("synthetic:candidate-context",),
            ),
        })
        result = run_analysis(
            "integrated-synthetic", handlers, bounded_through="discovery"
        )
        self.assertTrue(result.validation.valid, result.validation.issues)
        self.assertEqual(
            [receipt.stage_id for receipt in result.receipts],
            ["request_scope", "candidate_context", "search_plan", "discovery"],
        )
        self.assertEqual(calls, ["university admin", "research support"])
        self.assertEqual(
            result.context["search_execution_report"].attempted_call_count, 2
        )
        self.assertEqual(result.context["discovery_state"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
