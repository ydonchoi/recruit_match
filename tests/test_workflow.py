import unittest

from recruit_match.assessment import (
    CompensationQuote, DuplicateState, FitDimensions, RankingCandidate,
    RequirementCheck, RequirementStatus, VerificationState,
)
from recruit_match.assessment import EvidenceDomain
from recruit_match.domain import EligibilityState, RecommendationState
from recruit_match.pipeline import RunContract
from recruit_match.runner import StageExecution, execute_pipeline
from recruit_match.pipeline import StageStatus
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

    def test_synthetic_full_analysis_contract_runs_with_injected_stubs(self):
        contract = build_analysis_contract("synthetic-e2e")
        builtins = {"eligibility", "fit_assessment", "compensation_resolution", "ranking", "recommendation"}
        external = {}
        for stage_id in ANALYSIS_STAGE_IDS:
            if stage_id in builtins:
                continue
            if stage_id in ATTACHMENT_OPTIONAL_STAGES:
                external[stage_id] = lambda context, stage_id=stage_id: StageExecution(
                    StageStatus.NOT_APPLICABLE,
                    {},
                    evidence_refs=(f"synthetic:{stage_id}:no-attachment",),
                    reason="synthetic posting has no attachment",
                )
            else:
                stage_outputs = {
                    "candidate_context": {
                        "privacy_review_state": VerificationState.VERIFIED,
                        "schema_validation_state": VerificationState.VERIFIED,
                    },
                    "identity_resolution": {"duplicate_state": DuplicateState.RESOLVED},
                    "source_verification": {"source_verification_state": VerificationState.VERIFIED},
                    "currentness_verification": {"currentness_state": "ACTIVE"},
                    "recruitment_evidence": {"provenance_state": VerificationState.VERIFIED},
                }
                external[stage_id] = lambda context, stage_id=stage_id: StageExecution(
                    StageStatus.SUCCESS, stage_outputs.get(stage_id, {})
                )
        handlers = compose_analysis_handlers(external)
        initial_context = {
            "requirement_checks": [RequirementCheck(
                "degree", True, RequirementStatus.PASS,
                (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
                ("synthetic:candidate-degree", "synthetic:posting-degree"),
            )],
            "fit_dimensions": FitDimensions(90, 80, 70, 60),
            "fit_weights": (0.4, 0.3, 0.2, 0.1),
            "compensation_quotes": {
                "official": CompensationQuote("100-120", "synthetic:posting-salary", VerificationState.VERIFIED)
            },
            "ranking_candidates": [RankingCandidate("synthetic-opp-1", EligibilityState.PASS, 90, 80, 88, 1)],
        }
        result = execute_pipeline(contract, handlers, initial_context)
        self.assertTrue(result.validation.valid, result.validation.issues)
        self.assertEqual(result.context["eligibility"], EligibilityState.PASS)
        self.assertEqual(result.context["recommendation"], RecommendationState.RECOMMENDED)
        self.assertEqual(len(result.context["ranked_candidates"]), 1)
        self.assertEqual(len(result.receipts), len(ANALYSIS_STAGE_IDS))

    def test_unknown_boundary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "BOUNDARY_NOT_IN_RUN_SCOPE"):
            build_analysis_contract("synthetic-run", bounded_through="registry_write")


if __name__ == "__main__":
    unittest.main()
