import unittest

from recruit_match.assessment import (
    CompensationQuote,
    CompensationTier,
    DuplicateState,
    EvidenceDomain,
    FitDimensions,
    RankingCandidate,
    RecommendationInputs,
    RequirementCheck,
    RequirementStatus,
    VerificationState,
    decide_recommendation,
    evaluate_eligibility,
    rank_candidates,
    resolve_compensation,
    weighted_fit_score,
)
from recruit_match.domain import EligibilityState, RecommendationState


class AssessmentContractTests(unittest.TestCase):
    def test_empty_critical_requirements_never_pass(self):
        self.assertEqual(evaluate_eligibility([]), EligibilityState.UNKNOWN)

    def test_critical_failure_cannot_be_offset_by_other_passes(self):
        checks = [
            RequirementCheck("degree", True, RequirementStatus.PASS,
                             (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
                             ("candidate-degree-ref", "official-degree-requirement-ref")),
            RequirementCheck("license", True, RequirementStatus.FAIL,
                             (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
                             ("candidate-license-status-ref", "official-license-requirement-ref")),
            RequirementCheck("nice-to-have", False, RequirementStatus.PASS),
        ]
        self.assertEqual(evaluate_eligibility(checks), EligibilityState.FAIL)

    def test_fail_without_evidence_is_not_a_confirmed_failure(self):
        checks = [RequirementCheck("license", True, RequirementStatus.FAIL)]
        self.assertEqual(evaluate_eligibility(checks), EligibilityState.UNKNOWN)

    def test_evidence_backed_critical_failure_dominates_other_unknowns(self):
        checks = [
            RequirementCheck(
                "mandatory-license", True, RequirementStatus.FAIL,
                (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
                ("synthetic:candidate-license", "synthetic:official-license-rule"),
            ),
            RequirementCheck("degree", True, RequirementStatus.UNKNOWN),
        ]
        self.assertEqual(evaluate_eligibility(checks), EligibilityState.FAIL)

    def test_unsubstantiated_critical_failure_remains_unknown(self):
        checks = [
            RequirementCheck("mandatory-license", True, RequirementStatus.FAIL),
            RequirementCheck(
                "degree", True, RequirementStatus.PASS,
                (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
                ("synthetic:candidate-degree", "synthetic:official-degree-rule"),
            ),
        ]
        self.assertEqual(evaluate_eligibility(checks), EligibilityState.UNKNOWN)

    def test_unknown_critical_requirement_is_unknown(self):
        checks = [RequirementCheck("degree", True, RequirementStatus.PASS,
                                   (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
                                   ("candidate-degree-ref", "official-degree-requirement-ref")),
                  RequirementCheck("work-auth", True, RequirementStatus.UNKNOWN)]
        self.assertEqual(evaluate_eligibility(checks), EligibilityState.UNKNOWN)

    def test_candidate_and_recruitment_evidence_domains_are_explicit(self):
        check = RequirementCheck(
            "experience",
            True,
            RequirementStatus.PASS,
            (EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT),
            ("candidate-evidence-ref", "recruitment-evidence-ref"),
        )
        self.assertEqual(len(check.evidence_domains), 2)

    def test_boolean_fit_dimension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "FIT_SCORE_OUT_OF_RANGE:job_fit"):
            FitDimensions(True, 80, 70, 60)

    def test_boolean_fit_weight_is_rejected(self):
        dimensions = FitDimensions(100, 80, 60, 40)
        with self.assertRaisesRegex(ValueError, "INVALID_FIT_WEIGHTS"):
            weighted_fit_score(dimensions, (True, 0.2, 0.3, 0.4))

    def test_boolean_rank_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "RANK_LIMIT_MUST_BE_NONNEGATIVE_INTEGER"):
            rank_candidates([], limit=True)

    def test_invalid_location_priority_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_LOCATION_PRIORITY"):
            RankingCandidate("opp", EligibilityState.PASS, 80, 70, 75, True)

    def test_fit_score_remains_unknown_when_a_dimension_is_missing(self):
        dimensions = FitDimensions(90, 80, None, 70)
        self.assertIsNone(weighted_fit_score(dimensions, (0.4, 0.3, 0.2, 0.1)))

    def test_fit_score_uses_explicit_weights(self):
        dimensions = FitDimensions(100, 80, 60, 40)
        self.assertAlmostEqual(weighted_fit_score(dimensions, (0.5, 0.2, 0.2, 0.1)), 82.0)

    def test_official_compensation_has_precedence(self):
        result = resolve_compensation(
            official=CompensationQuote("100-120", "official-posting#salary", VerificationState.VERIFIED),
            institution_table=CompensationQuote("90-110", "institution-table#row-1", VerificationState.VERIFIED),
            estimate=CompensationQuote("80-100", "estimate#1", VerificationState.VERIFIED, ("regional benchmark",)),
        )
        self.assertEqual(result.tier, CompensationTier.OFFICIAL)
        self.assertEqual(result.confidence, "HIGH")

    def test_unverified_official_compensation_does_not_get_promoted(self):
        result = resolve_compensation(
            official=CompensationQuote("100-120", "official-posting#salary", VerificationState.UNKNOWN),
            institution_table=CompensationQuote("90-110", "institution-table#row-1", VerificationState.VERIFIED),
        )
        self.assertEqual(result.tier, CompensationTier.UNKNOWN)
        self.assertIn("COMPENSATION_SOURCE_NOT_VERIFIED", result.reason)

    def test_critical_pass_without_both_evidence_domains_is_unknown(self):
        result = evaluate_eligibility([
            RequirementCheck("degree", True, RequirementStatus.PASS,
                             (EvidenceDomain.CANDIDATE,), ("candidate-degree-ref",))
        ])
        self.assertEqual(result, EligibilityState.UNKNOWN)

    def test_non_finite_weights_are_rejected(self):
        dimensions = FitDimensions(100, 80, 60, 40)
        with self.assertRaisesRegex(ValueError, "INVALID_FIT_WEIGHTS"):
            weighted_fit_score(dimensions, (0.5, float("nan"), 0.2, 0.1))

    def test_estimate_requires_source_and_assumptions(self):
        result = resolve_compensation(estimate=CompensationQuote("80-100", "estimate#1", VerificationState.VERIFIED, ()))
        self.assertEqual(result.tier, CompensationTier.UNKNOWN)
        self.assertEqual(result.reason, "ESTIMATE_ASSUMPTIONS_MISSING")

    def test_compensation_quote_rejects_invalid_verification_type(self):
        with self.assertRaisesRegex(ValueError, "INVALID_COMPENSATION_VERIFICATION"):
            CompensationQuote("80-100", "estimate#1", "VERIFIED")

    def test_recommendation_inputs_reject_invalid_gate_types(self):
        with self.assertRaisesRegex(ValueError, "INVALID_RECOMMENDATION_GATE:privacy_review"):
            RecommendationInputs(
                eligibility=EligibilityState.PASS,
                source_verification=VerificationState.VERIFIED,
                currentness="ACTIVE",
                duplicate_state=DuplicateState.RESOLVED,
                privacy_review="VERIFIED",
                provenance=VerificationState.VERIFIED,
                schema_validation=VerificationState.VERIFIED,
            )

    def test_recommendation_rejects_wrong_input_object(self):
        with self.assertRaisesRegex(ValueError, "INVALID_RECOMMENDATION_INPUTS"):
            decide_recommendation({"eligibility": EligibilityState.PASS})

    def test_recommendation_requires_all_explicit_gates(self):
        result = decide_recommendation(RecommendationInputs(
            eligibility=EligibilityState.PASS,
            source_verification=VerificationState.VERIFIED,
            currentness="ACTIVE",
            duplicate_state=DuplicateState.RESOLVED,
            privacy_review=VerificationState.VERIFIED,
            provenance=VerificationState.VERIFIED,
            schema_validation=VerificationState.VERIFIED,
        ))
        self.assertEqual(result, RecommendationState.RECOMMENDED)

    def test_failed_provenance_blocks_recommendation(self):
        result = decide_recommendation(RecommendationInputs(
            eligibility=EligibilityState.PASS,
            source_verification=VerificationState.VERIFIED,
            currentness="ACTIVE",
            duplicate_state=DuplicateState.RESOLVED,
            privacy_review=VerificationState.VERIFIED,
            provenance=VerificationState.FAILED,
            schema_validation=VerificationState.VERIFIED,
        ))
        self.assertEqual(result, RecommendationState.NOT_RECOMMENDED)

    def test_unknown_gate_never_becomes_recommendation(self):
        result = decide_recommendation(RecommendationInputs(
            eligibility=EligibilityState.PASS,
            source_verification=VerificationState.VERIFIED,
            currentness="ACTIVE",
            duplicate_state=DuplicateState.RESOLVED,
            privacy_review=VerificationState.UNKNOWN,
            provenance=VerificationState.VERIFIED,
            schema_validation=VerificationState.VERIFIED,
        ))
        self.assertEqual(result, RecommendationState.NEEDS_REVIEW)

    def test_critical_eligibility_failure_forces_not_recommended(self):
        result = decide_recommendation(RecommendationInputs(
            eligibility=EligibilityState.FAIL,
            source_verification=VerificationState.VERIFIED,
            currentness="ACTIVE",
            duplicate_state=DuplicateState.RESOLVED,
            privacy_review=VerificationState.VERIFIED,
            provenance=VerificationState.VERIFIED,
            schema_validation=VerificationState.VERIFIED,
        ))
        self.assertEqual(result, RecommendationState.NOT_RECOMMENDED)

    def test_ranking_does_not_pad_and_missing_scores_sort_last(self):
        candidates = [
            RankingCandidate("a", EligibilityState.PASS, None, 80, 90, 1),
            RankingCandidate("b", EligibilityState.PASS, 90, 80, 70, 2),
            RankingCandidate("c", EligibilityState.UNKNOWN, 100, 100, 100, 0),
        ]
        result = rank_candidates(candidates, limit=50)
        self.assertEqual([item.opportunity_id for item in result], ["b", "a", "c"])
        self.assertEqual(len(result), 3)

    def test_malformed_compensation_quote_fails_closed(self):
        result = resolve_compensation(official=("100-120", "official-ref"))
        self.assertEqual(result.tier, CompensationTier.UNKNOWN)
        self.assertIn("COMPENSATION_QUOTE_INVALID", result.reason)

    def test_non_finite_ranking_score_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_RANKING_DIMENSION:job_fit"):
            RankingCandidate("opp", EligibilityState.PASS, float("nan"), 80, 70, 1)

    def test_hard_eligibility_failures_are_excluded_before_ranking(self):
        candidates = [
            RankingCandidate("pass", EligibilityState.PASS, 70, 70, 70, 1),
            RankingCandidate("unknown", EligibilityState.UNKNOWN, 100, 100, 100, 0),
            RankingCandidate("fail", EligibilityState.FAIL, 100, 100, 100, 0),
        ]
        result = rank_candidates(candidates, limit=50)
        self.assertEqual([item.opportunity_id for item in result], ["pass", "unknown"])

    def test_limit_zero_returns_no_records(self):
        self.assertEqual(rank_candidates([], limit=0), ())


if __name__ == "__main__":
    unittest.main()
