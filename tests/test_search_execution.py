import unittest
from types import SimpleNamespace

from recruit_match.search_budget import DEFAULT_CALLS, MAX_CALLS
from recruit_match.search_execution import (
    SearchCallStatus,
    SearchQueryPlan,
    execute_search_combinations,
    execute_search_plan,
    plans_from_combinations,
)


class SearchExecutionBudgetTests(unittest.TestCase):
    def plans(self, count):
        return tuple(
            SearchQueryPlan(i, f"combination-{i}", f"query {i}")
            for i in range(count)
        )

    def test_default_budget_is_20_calls(self):
        calls = []
        batch = execute_search_plan(
            self.plans(25), lambda query: calls.append(query) or (),
        )
        self.assertEqual(DEFAULT_CALLS, 20)
        self.assertEqual(batch.report.max_calls, 20)
        self.assertEqual(batch.report.attempted_call_count, 20)
        self.assertEqual(len(calls), 20)
        self.assertEqual(batch.report.skipped_query_count, 5)

    def test_maximum_budget_is_100_and_values_above_are_rejected(self):
        calls = []
        batch = execute_search_plan(
            self.plans(101), lambda query: calls.append(query) or (),
            max_calls=MAX_CALLS,
        )
        self.assertEqual(MAX_CALLS, 100)
        self.assertEqual(batch.report.attempted_call_count, 100)
        self.assertEqual(len(calls), 100)
        with self.assertRaisesRegex(ValueError, "SEARCH_CALL_BUDGET_MUST_BE_BETWEEN_1_AND_100"):
            execute_search_plan(self.plans(1), lambda query: calls.append(query) or (), max_calls=101)
        self.assertEqual(len(calls), 100)

    def test_executes_all_plans_when_budget_is_sufficient(self):
        calls = []
        batch = execute_search_plan(
            self.plans(3),
            lambda query: calls.append(query) or ({"query": query},),
            max_calls=3,
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(batch.report.planned_query_count, 3)
        self.assertEqual(batch.report.attempted_call_count, 3)
        self.assertEqual(batch.report.successful_call_count, 3)
        self.assertEqual(batch.report.failed_call_count, 0)
        self.assertEqual(batch.report.skipped_query_count, 0)
        self.assertEqual(len(batch.report.receipts), 3)

    def test_budget_caps_actual_callable_invocations(self):
        calls = []
        batch = execute_search_plan(
            self.plans(5),
            lambda query: calls.append(query) or (),
            max_calls=2,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(batch.report.attempted_call_count, 2)
        self.assertEqual(batch.report.skipped_query_count, 3)
        self.assertEqual(
            [r.status for r in batch.report.receipts],
            [
                SearchCallStatus.SUCCEEDED,
                SearchCallStatus.SUCCEEDED,
                SearchCallStatus.SKIPPED_BUDGET,
                SearchCallStatus.SKIPPED_BUDGET,
                SearchCallStatus.SKIPPED_BUDGET,
            ],
        )

    def test_provider_failure_consumes_one_call_and_does_not_retry(self):
        calls = []

        def provider(query):
            calls.append(query)
            raise RuntimeError("private details should not escape")

        batch = execute_search_plan(self.plans(2), provider, max_calls=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(batch.report.attempted_call_count, 2)
        self.assertEqual(batch.report.failed_call_count, 2)
        self.assertTrue(all(r.error_code == "PROVIDER_CALL_FAILED" for r in batch.report.receipts))
        self.assertNotIn("private details", repr(batch.report))

    def test_non_sequence_provider_result_is_a_failed_receipt(self):
        batch = execute_search_plan(
            self.plans(1), lambda query: {"not": "a sequence"}, max_calls=1
        )
        self.assertEqual(batch.report.failed_call_count, 1)
        self.assertEqual(batch.report.receipts[0].status, SearchCallStatus.FAILED)

    def test_provider_call_and_response_shape_failures_have_distinct_codes(self):
        call_failure = execute_search_plan(
            self.plans(1),
            lambda query: (_ for _ in ()).throw(TimeoutError("private detail")),
            max_calls=1,
        )
        shape_failure = execute_search_plan(
            self.plans(1), lambda query: {"not": "a sequence"}, max_calls=1
        )
        self.assertEqual(call_failure.report.receipts[0].error_code, "PROVIDER_CALL_FAILED")
        self.assertEqual(shape_failure.report.receipts[0].error_code, "PROVIDER_RESPONSE_NOT_SEQUENCE")
        self.assertNotIn("private detail", repr(call_failure.report))

    def test_duplicate_combination_ids_are_rejected_before_calls(self):
        calls = []
        plans = (
            SearchQueryPlan(0, "duplicate", "query A"),
            SearchQueryPlan(1, "duplicate", "query B"),
        )
        with self.assertRaisesRegex(ValueError, "SEARCH_PLAN_DUPLICATE_COMBINATION"):
            execute_search_plan(plans, lambda q: calls.append(q) or (), max_calls=2)
        self.assertEqual(calls, [])

    def test_duplicate_ordinals_are_rejected_before_calls(self):
        calls = []
        plans = (
            SearchQueryPlan(0, "combination-A", "query A"),
            SearchQueryPlan(0, "combination-B", "query B"),
        )
        with self.assertRaisesRegex(ValueError, "SEARCH_PLAN_DUPLICATE_ORDINAL"):
            execute_search_plan(plans, lambda q: calls.append(q) or (), max_calls=2)
        self.assertEqual(calls, [])

    def test_invalid_budget_is_rejected_before_calls(self):
        calls = []
        with self.assertRaisesRegex(ValueError, "SEARCH_CALL_BUDGET_MUST_BE_BETWEEN_1_AND_100"):
            execute_search_plan(self.plans(1), lambda q: calls.append(q) or (), max_calls=True)
        self.assertEqual(calls, [])

    def test_receipts_account_for_every_planned_query(self):
        batch = execute_search_plan(
            self.plans(4), lambda query: (query,), max_calls=1
        )
        self.assertEqual(len(batch.report.receipts), batch.report.planned_query_count)
        self.assertEqual(
            batch.report.attempted_call_count + batch.report.skipped_query_count,
            batch.report.planned_query_count,
        )

    def test_result_payloads_are_associated_with_plan_ordinals(self):
        batch = execute_search_plan(
            self.plans(2), lambda query: (query.upper(),), max_calls=2
        )
        self.assertEqual(batch.results_by_ordinal[0], ("QUERY 0",))
        self.assertEqual(batch.results_by_ordinal[1], ("QUERY 1",))

    def test_search_matrix_combinations_feed_budgeted_execution(self):
        combinations = (
            SimpleNamespace(combination_id="matrix-A", query="axis A"),
            SimpleNamespace(combination_id="matrix-B", query="axis B"),
            SimpleNamespace(combination_id="matrix-C", query="axis C"),
        )
        calls = []
        batch = execute_search_combinations(
            combinations, lambda query: calls.append(query) or (query,), max_calls=2
        )
        self.assertEqual(calls, ["axis A", "axis B"])
        self.assertEqual(batch.report.planned_query_count, 3)
        self.assertEqual(batch.report.attempted_call_count, 2)
        self.assertEqual(batch.report.skipped_query_count, 1)
        self.assertEqual(batch.report.receipts[-1].combination_id, "matrix-C")

    def test_matrix_combination_without_stable_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_SEARCH_COMBINATION_AT:0"):
            plans_from_combinations((SimpleNamespace(query="no stable ID"),))

    def test_empty_plan_has_zero_receipts_and_zero_calls(self):
        calls = []
        batch = execute_search_plan((), lambda query: calls.append(query) or (), max_calls=2)
        self.assertEqual(calls, [])
        self.assertEqual(batch.report.planned_query_count, 0)
        self.assertEqual(batch.report.attempted_call_count, 0)
        self.assertEqual(batch.report.receipts, ())


if __name__ == "__main__":
    unittest.main()
