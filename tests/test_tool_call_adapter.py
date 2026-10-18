import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from recruit_match.application import run_analysis
from recruit_match.pipeline import StageStatus
from recruit_match.runner import StageExecution
from recruit_match.search_stage import SearchProviderHit
from recruit_match.tool_call_adapter import (
    ToolCallPlan,
    ToolCallReceipt,
    ToolCallExecutionReport,
    ToolDispatchStatus,
    ToolExecutionConfirmation,
    ToolResponseValidation,
    build_tool_call_search_handlers,
    execute_tool_call_plan,
)


class ToolCallAdapterTests(unittest.TestCase):
    def setUp(self):
        self.plans = (
            ToolCallPlan(0, "run-1:matrix-A:web.search", "matrix-A", "web.search",
                         {"query": "university admin"}, "a" * 64),
            ToolCallPlan(1, "run-1:matrix-B:web.search", "matrix-B", "web.search",
                         {"query": "research support"}, "b" * 64),
        )

    def clock(self):
        return lambda: datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    def normalizer(self, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
            raise ValueError("bad provider response")
        return tuple(
            SearchProviderHit(str(item["id"]), str(item["title"]), str(item["url"]))
            for item in raw["results"]
        )

    def test_dispatches_plans_and_records_confirmed_validated_receipts(self):
        calls = []
        batch = execute_tool_call_plan(
            self.plans,
            lambda name, args: calls.append((name, args)) or {
                "results": [{"id": "r1", "title": "Notice", "url": "https://example.org/jobs/1"}]
            },
            self.normalizer,
            max_calls=2,
            allowed_tool_names=("web.search",),
            clock=self.clock(),
            run_id="run-1",
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(batch.report.attempted_dispatch_count, 2)
        self.assertEqual(batch.report.execution_confirmed_count, 2)
        self.assertEqual(batch.report.response_validated_count, 2)
        self.assertEqual(batch.report.response_rejected_count, 0)
        self.assertEqual(batch.report.receipts[0].execution_confirmation, ToolExecutionConfirmation.CONFIRMED)
        self.assertEqual(batch.report.receipts[0].response_validation, ToolResponseValidation.VALIDATED)

    def test_budget_caps_dispatcher_invocations_and_marks_unattempted_calls(self):
        calls = []
        batch = execute_tool_call_plan(
            self.plans + (ToolCallPlan(2, "run-1:matrix-C:web.search", "matrix-C", "web.search",
                                      {"query": "policy research"}, "c" * 64),),
            lambda name, args: calls.append(args) or {"results": []},
            self.normalizer,
            max_calls=1,
            allowed_tool_names=("web.search",),
            clock=self.clock(),
            run_id="run-1",
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(batch.report.skipped_call_count, 2)
        self.assertEqual(batch.report.receipts[1].status, ToolDispatchStatus.SKIPPED_BUDGET)
        self.assertFalse(batch.report.receipts[1].dispatch_attempted)
        self.assertEqual(batch.report.receipts[1].execution_confirmation, ToolExecutionConfirmation.NOT_ATTEMPTED)

    def test_dispatch_exception_is_unknown_and_is_not_retried(self):
        calls = []
        def dispatcher(name, args):
            calls.append(args)
            raise TimeoutError("sensitive response")
        batch = execute_tool_call_plan(
            self.plans[:1], dispatcher, self.normalizer, max_calls=1,
            allowed_tool_names=("web.search",), clock=self.clock(), run_id="run-1",
        )
        self.assertEqual(len(calls), 1)
        receipt = batch.report.receipts[0]
        self.assertEqual(receipt.status, ToolDispatchStatus.FAILED)
        self.assertEqual(receipt.execution_confirmation, ToolExecutionConfirmation.UNKNOWN)
        self.assertEqual(receipt.error_code, "TOOL_DISPATCH_EXCEPTION")
        self.assertNotIn("sensitive response", repr(receipt))

    def test_returned_but_malformed_response_is_confirmed_but_rejected(self):
        batch = execute_tool_call_plan(
            self.plans[:1], lambda name, args: {"unexpected": "shape"},
            self.normalizer, max_calls=1, allowed_tool_names=("web.search",),
            clock=self.clock(), run_id="run-1",
        )
        receipt = batch.report.receipts[0]
        self.assertEqual(receipt.status, ToolDispatchStatus.SUCCEEDED)
        self.assertEqual(receipt.execution_confirmation, ToolExecutionConfirmation.CONFIRMED)
        self.assertEqual(receipt.response_validation, ToolResponseValidation.REJECTED)
        self.assertEqual(batch.report.response_rejected_count, 1)
        self.assertEqual(batch.report.response_validated_count, 0)

    def test_allowlist_rejection_occurs_before_dispatch(self):
        calls = []
        with self.assertRaisesRegex(ValueError, "TOOL_NAME_NOT_ALLOWLISTED"):
            execute_tool_call_plan(
                self.plans, lambda name, args: calls.append(name), self.normalizer,
                max_calls=2, allowed_tool_names=("web.fetch",), run_id="run-1",
            )
        self.assertEqual(calls, [])

    def test_duplicate_call_ids_are_rejected_before_dispatch(self):
        duplicate = (self.plans[0], ToolCallPlan(
            1, self.plans[0].call_id, "matrix-B", "web.search",
            {"query": "another"}, "b" * 64
        ))
        calls = []
        with self.assertRaisesRegex(ValueError, "TOOL_CALL_DUPLICATE_CALL_ID"):
            execute_tool_call_plan(
                duplicate, lambda name, args: calls.append(args), self.normalizer,
                max_calls=2, allowed_tool_names=("web.search",), run_id="run-1",
            )
        self.assertEqual(calls, [])

    def test_duplicate_combination_ids_are_rejected_before_dispatch(self):
        duplicate = (self.plans[0], ToolCallPlan(
            1, "different-call", "matrix-A", "web.search",
            {"query": "another"}, "b" * 64
        ))
        with self.assertRaisesRegex(ValueError, "TOOL_CALL_DUPLICATE_COMBINATION_ID"):
            execute_tool_call_plan(
                duplicate, lambda name, args: {}, self.normalizer,
                max_calls=2, allowed_tool_names=("web.search",), run_id="run-1",
            )

    def test_bool_budget_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "TOOL_CALL_BUDGET_MUST_BE_POSITIVE_INTEGER"):
            execute_tool_call_plan(
                self.plans, lambda name, args: {}, self.normalizer,
                max_calls=True, allowed_tool_names=("web.search",), run_id="run-1",
            )

    def test_arguments_are_defensively_copied_before_dispatch(self):
        plan = ToolCallPlan(0, "call", "matrix-A", "web.search",
                            {"query": "one", "filters": {"types": ["job"]}}, "a" * 64)
        def dispatcher(name, args):
            args["filters"]["types"].append("mutated")
            return {"results": []}
        execute_tool_call_plan(
            (plan,), dispatcher, self.normalizer, max_calls=1,
            allowed_tool_names=("web.search",), clock=self.clock(), run_id="run-1",
        )
        self.assertEqual(plan.arguments["filters"]["types"], ["job"])

    def test_stage_adapter_blocks_partial_budget_run_and_preserves_receipts(self):
        combinations = (
            SimpleNamespace(combination_id="matrix-A", query="university admin"),
            SimpleNamespace(combination_id="matrix-B", query="research support"),
        )
        calls = []
        handlers = build_tool_call_search_handlers(
            run_id="run-partial",
            planner=lambda context: combinations,
            dispatcher=lambda name, args: calls.append(args) or {"results": []},
            result_normalizer=self.normalizer,
            tool_name="web.search",
            allowed_tool_names=("web.search",),
            max_planned_combinations=3,
            max_calls=1,
            clock=self.clock(),
        )
        handlers.update({
            "request_scope": lambda context: StageExecution(StageStatus.SUCCESS, {"scope": "bounded"}),
            "candidate_context": lambda context: StageExecution(
                StageStatus.SUCCESS, {"candidate_context_ref": "synthetic:candidate"},
                evidence_refs=("synthetic:candidate",),
            ),
        })
        result = run_analysis("run-partial", handlers, bounded_through="discovery")
        self.assertFalse(result.validation.valid)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.receipts[-1].status, StageStatus.BLOCKED)
        self.assertEqual(result.context["tool_call_execution_report"].skipped_call_count, 1)
        self.assertFalse(result.context["discovery_complete"])

    def test_stage_adapter_integrates_into_bounded_run(self):
        combinations = (
            SimpleNamespace(combination_id="matrix-A", query="university admin"),
            SimpleNamespace(combination_id="matrix-B", query="research support"),
        )
        calls = []
        handlers = build_tool_call_search_handlers(
            run_id="run-full-search",
            planner=lambda context: combinations,
            dispatcher=lambda name, args: calls.append((name, args)) or {
                "results": [{"id": f"r{len(calls)}", "title": "Notice", "url": "https://example.org/job"}]
            },
            result_normalizer=self.normalizer,
            tool_name="web.search",
            allowed_tool_names=("web.search",),
            max_planned_combinations=3,
            max_calls=2,
            clock=self.clock(),
        )
        handlers.update({
            "request_scope": lambda context: StageExecution(StageStatus.SUCCESS, {"scope": "bounded"}),
            "candidate_context": lambda context: StageExecution(
                StageStatus.SUCCESS, {"candidate_context_ref": "synthetic:candidate"},
                evidence_refs=("synthetic:candidate",),
            ),
        })
        result = run_analysis("run-full-search", handlers, bounded_through="discovery")
        self.assertTrue(result.validation.valid, result.validation.issues)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.context["tool_call_execution_report"].response_validated_count, 2)
        self.assertEqual(len(result.context["discovered_search_results"]), 2)

    def test_url_validation_rejects_credentials_in_normalized_result(self):
        with self.assertRaisesRegex(ValueError, "SEARCH_RESULT_URL_CREDENTIALS_FORBIDDEN"):
            self.normalizer({"results": [{"id": "r1", "title": "bad", "url": "https://u:p@example.org"}]})


if __name__ == "__main__":
    unittest.main()
