import unittest

from recruit_match.application import run_analysis
from recruit_match.pipeline import StageStatus
from recruit_match.runner import StageExecution


class ApplicationEntryPointTests(unittest.TestCase):
    def test_missing_external_adapter_fails_closed_at_first_stage(self):
        result = run_analysis("synthetic-run", {})
        self.assertFalse(result.validation.valid)
        self.assertEqual(result.receipts[0].stage_id, "request_scope")
        self.assertEqual(result.receipts[0].status, StageStatus.BLOCKED)
        self.assertEqual(result.receipts[0].reason, "HANDLER_NOT_CONFIGURED")

    def test_bounded_run_can_execute_with_explicit_handler(self):
        result = run_analysis(
            "synthetic-run",
            {"request_scope": lambda context: StageExecution(StageStatus.SUCCESS, {})},
            bounded_through="request_scope",
        )
        self.assertTrue(result.validation.valid, result.validation.issues)
        self.assertEqual([receipt.stage_id for receipt in result.receipts], ["request_scope"])

    def test_unknown_adapter_name_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_ANALYSIS_HANDLER"):
            run_analysis("synthetic-run", {"unexpected": lambda context: StageExecution(StageStatus.SUCCESS, {})})

    def test_invalid_initial_context_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "INITIAL_CONTEXT_MUST_BE_MAPPING"):
            run_analysis("synthetic-run", {}, initial_context=[])


if __name__ == "__main__":
    unittest.main()
