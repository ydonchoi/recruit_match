import unittest

from recruit_match.assessment import (
    CompensationQuote,
    CompensationTier,
    DuplicateState,
    EligibilityState,
    FitDimensions,
    RankingCandidate,
    RecommendationInputs,
    RequirementCheck,
    RequirementStatus,
    VerificationState,
)
from recruit_match.assessment_handlers import build_assessment_handlers
from recruit_match.domain import CurrentnessState, RecommendationState
from recruit_match.pipeline import RunContract, StageSpec, StageStatus
from recruit_match.runner import execute_pipeline, StageExecution


class AssessmentHandlerTests(unittest.TestCase):
    def setUp(self):
        self.handlers = build_assessment_handlers()

    def run_one(self, stage_id, context):
        return execute_pipeline(
            RunContract("synthetic-run", (StageSpec(stage_id),)),
            {stage_id: self.handlers[stage_id]},
            context,
        )

    def test_missing_eligibility_input_blocks_stage(self):
        result = self.run_one("eligibility", {})
        self.assertFalse(result.validation.valid)
        self.assertEqual(result.receipts[0].status, StageStatus.BLOCKED)

    def test_eligibility_unknown_is_a_successful_assessment_not_a_pass(self):
        result = self.run_one("eligibility", {
            "requirement_checks": [RequirementCheck("degree", True, RequirementStatus.UNKNOWN)]
        })
        self.assertTrue(result.validation.valid)
        self.assertEqual(result.context["eligibility"], EligibilityState.UNKNOWN)

    def test_fit_missing_dimension_remains_unknown(self):
        result = self.run_one("fit_assessment", {
            "fit_dimensions": FitDimensions(90, 80, None, 70),
            "fit_weights": (0.4, 0.3, 0.2, 0.1),
        })
        self.assertTrue(result.validation.valid)
        self.assertIsNone(result.context["fit_score"])
        self.assertEqual(result.context["fit_state"], "UNKNOWN")

    def test_unverified_compensation_does_not_become_official(self):
        result = self.run_one("compensation_resolution", {
            "compensation_quotes": {
                "official": CompensationQuote("100-120", "source-ref", VerificationState.UNKNOWN)
            }
        })
        self.assertTrue(result.validation.valid)
        self.assertEqual(result.context["compensation"].tier, CompensationTier.UNKNOWN)

    def test_ranking_handler_rejects_boolean_limit(self):
        result = self.run_one("ranking", {
            "ranking_candidates": [],
            "ranking_limit": True,
        })
        self.assertFalse(result.validation.valid)
        self.assertEqual(result.receipts[0].status, StageStatus.BLOCKED)
        self.assertEqual(result.receipts[0].reason, "RANKING_LIMIT_INVALID")

    def test_ranking_handler_does_not_pad_shortlists(self):
        result = self.run_one("ranking", {
            "ranking_candidates": [
                RankingCandidate("one", EligibilityState.PASS, 80, 75, 70, 1)
            ],
            "ranking_limit": 50,
        })
        self.assertTrue(result.validation.valid)
        self.assertEqual(len(result.context["ranked_candidates"]), 1)

    def test_missing_recommendation_gate_blocks_stage(self):
        result = self.run_one("recommendation", {
            "eligibility": EligibilityState.PASS,
            "source_verification_state": VerificationState.VERIFIED,
            "currentness_state": CurrentnessState.ACTIVE,
            "duplicate_state": DuplicateState.RESOLVED,
            "privacy_review_state": VerificationState.UNKNOWN,
            "provenance_state": VerificationState.VERIFIED,
        })
        self.assertFalse(result.validation.valid)
        self.assertEqual(result.receipts[0].status, StageStatus.BLOCKED)
        self.assertIn("schema_validation_state", result.receipts[0].reason)

    def test_unknown_recommendation_gate_produces_review_state(self):
        result = self.run_one("recommendation", {
            "eligibility": EligibilityState.PASS,
            "source_verification_state": VerificationState.VERIFIED,
            "currentness_state": CurrentnessState.ACTIVE,
            "duplicate_state": DuplicateState.RESOLVED,
            "privacy_review_state": VerificationState.UNKNOWN,
            "provenance_state": VerificationState.VERIFIED,
            "schema_validation_state": VerificationState.VERIFIED,
        })
        self.assertTrue(result.validation.valid)
        self.assertEqual(result.context["recommendation"], RecommendationState.NEEDS_REVIEW)

    def test_critical_eligibility_failure_propagates_to_recommendation(self):
        from recruit_match.assessment import EvidenceDomain
        contract = RunContract("synthetic-run", (
            StageSpec("eligibility"),
            StageSpec("recommendation", predecessors=("eligibility",)),
        ))
        result = execute_pipeline(contract, self.handlers, {
            "requirement_checks": [RequirementCheck(
                "mandatory-license", True, RequirementStatus.FAIL,
                (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
                ("synthetic:candidate-license", "synthetic:official-license-requirement"),
            )],
            "source_verification_state": VerificationState.VERIFIED,
            "currentness_state": CurrentnessState.ACTIVE,
            "duplicate_state": DuplicateState.RESOLVED,
            "privacy_review_state": VerificationState.VERIFIED,
            "provenance_state": VerificationState.VERIFIED,
            "schema_validation_state": VerificationState.VERIFIED,
        })
        self.assertTrue(result.validation.valid)
        self.assertEqual(result.context["eligibility"], EligibilityState.FAIL)
        self.assertEqual(result.context["recommendation"], RecommendationState.NOT_RECOMMENDED)


if __name__ == "__main__":
    unittest.main()
