import unittest

from recruit_match.pipeline import RunContract
from recruit_match.workflow import (
    ANALYSIS_STAGE_IDS,
    ATTACHMENT_OPTIONAL_STAGES,
    build_analysis_contract,
    compose_analysis_handlers,
)


class WorkflowContractTests(unittest.TestCase):
    def test_declares_full_analysis_path_in_order(self):
        contract = build_analysis_contract("synthetic-run")
        self.assertEqual(contract.in_scope_stage_ids, ANALYSIS_STAGE_IDS)
        self.assertEqual(len(contract.stages), 18)

    def test_stage_chain_is_explicit(self):
        contract = build_analysis_contract("synthetic-run")
        for index, stage in enumerate(contract.stages):
            expected = () if index == 0 else (contract.stages[index - 1].stage_id,)
            self.assertEqual(stage.predecessors, expected)

    def test_only_attachment_stages_allow_not_applicable(self):
        contract = build_analysis_contract("synthetic-run")
        allowed = {stage.stage_id for stage in contract.stages if stage.allow_not_applicable}
        self.assertEqual(allowed, set(ATTACHMENT_OPTIONAL_STAGES))

    def test_bounded_run_stops_at_named_stage(self):
        contract = build_analysis_contract("synthetic-run", bounded_through="source_verification")
        self.assertEqual(
            contract.in_scope_stage_ids,
            ANALYSIS_STAGE_IDS[: ANALYSIS_STAGE_IDS.index("source_verification") + 1],
        )

    def test_unknown_external_handler_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_ANALYSIS_HANDLER"):
            compose_analysis_handlers({"not_a_stage": lambda context: None})

    def test_assessment_handlers_cannot_be_overridden(self):
        with self.assertRaisesRegex(ValueError, "ASSESSMENT_HANDLER_OVERRIDE_FORBIDDEN"):
            compose_analysis_handlers({"eligibility": lambda context: None})

    def test_unknown_boundary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "BOUNDARY_NOT_IN_RUN_SCOPE"):
            build_analysis_contract("synthetic-run", bounded_through="registry_write")


if __name__ == "__main__":
    unittest.main()
