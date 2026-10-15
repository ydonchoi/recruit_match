import unittest

from recruit_match.pipeline import RunContract, StageSpec, StageStatus
from recruit_match.runner import StageExecution, execute_pipeline


class PipelineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.contract = RunContract(
            run_id="synthetic-run",
            stages=(
                StageSpec("discover"),
                StageSpec("verify", predecessors=("discover",)),
                StageSpec("assess", predecessors=("verify",)),
            ),
        )

    def test_successful_handlers_run_in_order_and_pass_context(self):
        calls = []
        def discover(context):
            calls.append("discover")
            return StageExecution(StageStatus.SUCCESS, {"opportunity_count": 2})
        def verify(context):
            calls.append(("verify", context["opportunity_count"]))
            return StageExecution(StageStatus.SUCCESS, {"verified_count": 1})
        def assess(context):
            calls.append(("assess", context["verified_count"]))
            return StageExecution(StageStatus.SUCCESS, {"recommendation_count": 1})

        result = execute_pipeline(
            self.contract,
            {"discover": discover, "verify": verify, "assess": assess},
        )
        self.assertTrue(result.validation.valid)
        self.assertEqual(calls, ["discover", ("verify", 2), ("assess", 1)])

    def test_missing_handler_blocks_and_stops(self):
        calls = []
        result = execute_pipeline(
            self.contract,
            {"discover": lambda context: StageExecution(StageStatus.SUCCESS, {})},
        )
        self.assertFalse(result.validation.valid)
        self.assertEqual([r.stage_id for r in result.receipts], ["discover", "verify"])
        self.assertEqual(result.receipts[-1].status, StageStatus.BLOCKED)

    def test_handler_exception_is_sanitized_and_stops(self):
        calls = []
        def discover(context):
            raise RuntimeError("sensitive source text should not leak")
        result = execute_pipeline(
            self.contract,
            {
                "discover": discover,
                "verify": lambda context: (calls.append("verify") or StageExecution(StageStatus.SUCCESS, {})),
            },
        )
        self.assertFalse(result.validation.valid)
        self.assertEqual(result.receipts[0].reason, "STAGE_HANDLER_EXCEPTION")
        self.assertEqual(calls, [])

    def test_failed_stage_does_not_execute_downstream(self):
        calls = []
        result = execute_pipeline(
            self.contract,
            {
                "discover": lambda context: StageExecution(
                    StageStatus.BLOCKED, {}, reason="policy denied"
                ),
                "verify": lambda context: (calls.append("verify") or StageExecution(StageStatus.SUCCESS, {})),
            },
        )
        self.assertFalse(result.validation.valid)
        self.assertEqual(calls, [])
        self.assertEqual(result.receipts[0].status, StageStatus.BLOCKED)

    def test_bounded_run_does_not_claim_later_stages(self):
        bounded = RunContract(
            run_id="synthetic-run",
            stages=self.contract.stages,
            bounded_through="verify",
        )
        result = execute_pipeline(
            bounded,
            {
                "discover": lambda context: StageExecution(StageStatus.SUCCESS, {}),
                "verify": lambda context: StageExecution(StageStatus.SUCCESS, {}),
            },
        )
        self.assertTrue(result.validation.valid)
        self.assertEqual([r.stage_id for r in result.receipts], ["discover", "verify"])


if __name__ == "__main__":
    unittest.main()
