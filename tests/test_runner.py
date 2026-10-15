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

    def test_invalid_handler_registry_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "INVALID_HANDLER_REGISTRY"):
            execute_pipeline(self.contract, {"discover": "not-callable"})

    def test_invalid_initial_context_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "INITIAL_CONTEXT_MUST_BE_MAPPING"):
            execute_pipeline(self.contract, {}, initial_context=[])

    def test_non_string_initial_context_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "INITIAL_CONTEXT_KEYS_MUST_BE_STRINGS"):
            execute_pipeline(self.contract, {}, initial_context={1: "value"})

    def test_handler_cannot_mutate_shared_nested_context_in_place(self):
        initial = {"items": ["original"]}
        def mutate(context):
            context["items"].append("handler-mutation")
            return StageExecution(StageStatus.SUCCESS, {"observed": tuple(context["items"])})
        result = execute_pipeline(
            RunContract("isolation-run", (StageSpec("mutate"), StageSpec("observe", predecessors=("mutate",)))),
            {
                "mutate": mutate,
                "observe": lambda context: StageExecution(
                    StageStatus.SUCCESS, {"observed_after": tuple(context["items"])}
                ),
            },
            initial,
        )
        self.assertEqual(initial["items"], ["original"])
        self.assertEqual(result.context["items"], ["original"])
        self.assertEqual(result.context["observed"], ("original", "handler-mutation"))
        self.assertEqual(result.context["observed_after"], ("original",))

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

    def test_not_applicable_without_permission_does_not_execute_downstream(self):
        calls = []
        result = execute_pipeline(
            self.contract,
            {
                "discover": lambda context: StageExecution(
                    StageStatus.NOT_APPLICABLE, {}, reason="no source configured"
                ),
                "verify": lambda context: (calls.append("verify") or StageExecution(StageStatus.SUCCESS, {})),
            },
        )
        self.assertFalse(result.validation.valid)
        self.assertEqual(calls, [])
        self.assertIn("NOT_APPLICABLE_NOT_ALLOWED:discover", result.validation.issues)

    def test_evidence_required_stage_fails_closed_without_refs(self):
        contract = RunContract("synthetic-evidence", (StageSpec("source", evidence_required=True),))
        result = execute_pipeline(
            contract,
            {"source": lambda context: StageExecution(StageStatus.SUCCESS, {"source": "present"})},
        )
        self.assertFalse(result.validation.valid)
        self.assertEqual(result.receipts[0].status, StageStatus.FAILED)
        self.assertEqual(result.receipts[0].reason, "STAGE_EVIDENCE_MISSING")
        self.assertNotIn("source", result.context)

    def test_malformed_evidence_refs_fail_closed(self):
        contract = RunContract("synthetic-evidence", (StageSpec("source", evidence_required=True),))
        result = execute_pipeline(
            contract,
            {"source": lambda context: StageExecution(
                StageStatus.SUCCESS, {}, evidence_refs=("",)
            )},
        )
        self.assertFalse(result.validation.valid)
        self.assertEqual(result.receipts[0].status, StageStatus.FAILED)
        self.assertEqual(result.receipts[0].reason, "STAGE_HANDLER_EXCEPTION")

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
