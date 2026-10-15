import unittest

from recruit_match.pipeline import (
    RunContract,
    StageReceipt,
    StageSpec,
    StageStatus,
    validate_run,
)


class PipelineContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = RunContract(
            run_id="run-synthetic-001",
            stages=(
                StageSpec("discover"),
                StageSpec("verify", predecessors=("discover",)),
                StageSpec("assess", predecessors=("verify",)),
            ),
        )

    def receipt(self, stage_id, status=StageStatus.SUCCESS, **kwargs):
        predecessors = {
            "discover": (),
            "verify": ("discover",),
            "assess": ("verify",),
        }[stage_id]
        return StageReceipt(
            run_id="run-synthetic-001",
            stage_id=stage_id,
            status=status,
            attempt=1,
            predecessor_stage_ids=predecessors,
            reason=kwargs.get("reason"),
            evidence_refs=kwargs.get("evidence_refs", ()),
        )

    def test_complete_chain_is_valid(self):
        result = validate_run(
            self.contract,
            [self.receipt("discover"), self.receipt("verify"), self.receipt("assess")],
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.completed_stage_ids, ("discover", "verify", "assess"))

    def test_missing_required_stage_fails(self):
        result = validate_run(self.contract, [self.receipt("discover")])
        self.assertFalse(result.valid)
        self.assertIn("MISSING_TERMINAL_RECEIPT:verify", result.issues)
        self.assertIn("MISSING_TERMINAL_RECEIPT:assess", result.issues)

    def test_failed_predecessor_blocks_downstream_acceptance(self):
        result = validate_run(
            self.contract,
            [
                self.receipt("discover", StageStatus.FAILED, reason="source unavailable"),
                self.receipt("verify"),
                self.receipt("assess"),
            ],
        )
        self.assertFalse(result.valid)
        self.assertIn(
            "PREDECESSOR_NOT_TERMINALLY_ACCEPTABLE:verify:discover", result.issues
        )
        self.assertNotIn("verify", result.completed_stage_ids)
        self.assertNotIn("assess", result.completed_stage_ids)

    def test_bounded_run_is_explicit(self):
        bounded = RunContract(
            run_id="run-synthetic-001",
            stages=self.contract.stages,
            bounded_through="verify",
        )
        result = validate_run(bounded, [self.receipt("discover"), self.receipt("verify")])
        self.assertTrue(result.valid)
        self.assertNotIn("assess", result.completed_stage_ids)

    def test_unapproved_not_applicable_is_rejected(self):
        result = validate_run(
            self.contract,
            [
                self.receipt("discover", StageStatus.NOT_APPLICABLE, reason="not permitted"),
                self.receipt("verify"),
                self.receipt("assess"),
            ],
        )
        self.assertFalse(result.valid)
        self.assertIn("NOT_APPLICABLE_NOT_ALLOWED:discover", result.issues)

    def test_non_success_requires_reason(self):
        with self.assertRaisesRegex(ValueError, "NON_SUCCESS_REQUIRES_REASON"):
            StageReceipt(
                run_id="run-synthetic-001",
                stage_id="discover",
                status=StageStatus.BLOCKED,
                attempt=1,
            )

    def test_final_stage_failure_invalidates_run(self):
        result = validate_run(
            self.contract,
            [
                self.receipt("discover"),
                self.receipt("verify"),
                self.receipt("assess", StageStatus.FAILED, reason="assessment error"),
            ],
        )
        self.assertFalse(result.valid)
        self.assertIn("STAGE_TERMINAL_NOT_SUCCESS:assess:FAILED", result.issues)

    def test_not_applicable_requires_evidence_reference(self):
        with self.assertRaisesRegex(ValueError, "NOT_APPLICABLE_REQUIRES_EVIDENCE"):
            StageReceipt(
                run_id="run-synthetic-001",
                stage_id="discover",
                status=StageStatus.NOT_APPLICABLE,
                attempt=1,
                reason="no source configured",
            )

    def test_evidence_required_stage_rejects_missing_evidence(self):
        contract = RunContract("run-synthetic-001", (StageSpec("discover", evidence_required=True),))
        receipt = StageReceipt(
            run_id="run-synthetic-001", stage_id="discover", status=StageStatus.SUCCESS,
            attempt=1,
        )
        result = validate_run(contract, [receipt])
        self.assertFalse(result.valid)
        self.assertIn("STAGE_EVIDENCE_MISSING:discover", result.issues)

    def test_evidence_required_stage_accepts_evidence_reference(self):
        contract = RunContract("run-synthetic-001", (StageSpec("discover", evidence_required=True),))
        receipt = StageReceipt(
            run_id="run-synthetic-001", stage_id="discover", status=StageStatus.SUCCESS,
            attempt=1, evidence_refs=("synthetic:source-receipt",),
        )
        result = validate_run(contract, [receipt])
        self.assertTrue(result.valid, result.issues)

    def test_duplicate_receipt_fails(self):
        result = validate_run(
            self.contract,
            [self.receipt("discover"), self.receipt("discover")],
        )
        self.assertFalse(result.valid)
        self.assertIn("DUPLICATE_TERMINAL_RECEIPT:discover", result.issues)


if __name__ == "__main__":
    unittest.main()
