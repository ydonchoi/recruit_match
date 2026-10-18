import unittest

from recruit_match.domain import (
    ApplicationOutcome,
    CurrentnessState,
    EligibilityState,
    ExecutionReadiness,
    LifecycleState,
    OpportunityRecord,
    RecommendationState,
    SourceVerificationState,
    validate_record,
)


class DomainValidationTests(unittest.TestCase):
    def make_record(self, **overrides):
        values = {
            "registry_id": "reg-synthetic-001",
            "opportunity_id": "opp-synthetic-001",
            "organization": "Example Corp",
            "position": "Research Engineer",
            "recruitment_cycle": "cycle-synthetic-001",
            "posting_id": "posting-synthetic-001",
            "source_url": "https://example.com/jobs/1",
            "source_verification": SourceVerificationState.VERIFIED,
            "currentness": CurrentnessState.ACTIVE,
            "lifecycle_state": LifecycleState.ACTIVE,
            "eligibility": EligibilityState.UNKNOWN,
            "recommendation": RecommendationState.UNKNOWN,
            "application_outcome": ApplicationOutcome.NOT_APPLIED,
            "execution_readiness": ExecutionReadiness.UNKNOWN,
        }
        values.update(overrides)
        return OpportunityRecord(**values)

    def test_valid_record_has_no_issues(self):
        self.assertEqual(validate_record(self.make_record()), [])

    def test_missing_lifecycle_is_not_assumed_active(self):
        record = self.make_record(lifecycle_state=LifecycleState.UNKNOWN)
        issues = validate_record(record)
        self.assertIn("LIFECYCLE_UNKNOWN", {issue.code for issue in issues})

    def test_source_url_does_not_equal_source_verification(self):
        record = self.make_record(source_verification=SourceVerificationState.UNKNOWN)
        self.assertEqual(validate_record(record), [])
        self.assertEqual(record.source_verification, SourceVerificationState.UNKNOWN)

    def test_verification_without_source_is_rejected(self):
        record = self.make_record(source_url=None, source_verification=SourceVerificationState.VERIFIED)
        issues = validate_record(record)
        self.assertIn(
            "SOURCE_VERIFICATION_WITHOUT_SOURCE",
            {issue.code for issue in issues},
        )

    def test_required_text_fields_are_not_silently_defaulted(self):
        record = self.make_record(organization=" ", position="")
        issues = validate_record(record)
        fields = {
            issue.field
            for issue in issues
            if issue.code == "REQUIRED_FIELD_MISSING"
        }
        self.assertEqual(fields, {"organization", "position"})

    def test_application_outcome_and_readiness_are_separate(self):
        record = self.make_record(
            application_outcome=ApplicationOutcome.REJECTED,
            execution_readiness=ExecutionReadiness.READY,
        )
        self.assertEqual(record.application_outcome, ApplicationOutcome.REJECTED)
        self.assertEqual(record.execution_readiness, ExecutionReadiness.READY)

    def test_eligibility_and_recommendation_are_independent(self):
        record = self.make_record(
            eligibility=EligibilityState.FAIL,
            recommendation=RecommendationState.RECOMMENDED,
        )
        self.assertEqual(record.eligibility, EligibilityState.FAIL)
        self.assertEqual(record.recommendation, RecommendationState.RECOMMENDED)

    def test_invalid_enum_values_are_reported(self):
        record = self.make_record(source_verification="VERIFIED")
        issues = validate_record(record)
        self.assertIn("INVALID_ENUM_VALUE", {issue.code for issue in issues})

    def test_non_https_source_url_is_rejected(self):
        record = self.make_record(source_url="http://example.com/jobs/1")
        issues = validate_record(record)
        self.assertIn("SOURCE_URL_NOT_HTTPS", {issue.code for issue in issues})

    def test_source_url_with_invalid_port_is_rejected(self):
        record = self.make_record(source_url="https://example.com:invalid/jobs/1")
        issues = validate_record(record)
        self.assertIn("SOURCE_URL_NOT_HTTPS", {issue.code for issue in issues})

    def test_invalid_optional_identity_fields_are_reported(self):
        record = self.make_record(recruitment_cycle=" ", posting_id=42)
        issues = validate_record(record)
        self.assertEqual(
            {(issue.code, issue.field) for issue in issues if issue.code == "INVALID_OPTIONAL_TEXT"},
            {("INVALID_OPTIONAL_TEXT", "recruitment_cycle"), ("INVALID_OPTIONAL_TEXT", "posting_id")},
        )

    def test_wrong_record_type_returns_validation_issue(self):
        issues = validate_record(None)
        self.assertEqual([issue.code for issue in issues], ["INVALID_RECORD_TYPE"])

    def test_currentness_supports_closing_soon_and_expired(self):
        self.assertEqual(CurrentnessState.CLOSING_SOON.value, "CLOSING_SOON")
        self.assertEqual(CurrentnessState.EXPIRED.value, "EXPIRED")

    def test_sync_state_is_not_part_of_the_domain_record(self):
        fields = set(OpportunityRecord.__dataclass_fields__)
        self.assertNotIn("sync_state", fields)


if __name__ == "__main__":
    unittest.main()
