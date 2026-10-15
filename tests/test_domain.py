import unittest

from recruit_match.domain import (
    ApplicationOutcome,
    ExecutionReadiness,
    LifecycleState,
    OpportunityRecord,
    SyncState,
    validate_record,
)


class DomainValidationTests(unittest.TestCase):
    def make_record(self, **overrides):
        values = {
            "registry_id": "reg-001",
            "opportunity_id": "opp-001",
            "organization": "Example Corp",
            "position": "Research Engineer",
            "source_url": "https://example.com/jobs/1",
            "source_verified": True,
            "lifecycle_state": LifecycleState.ACTIVE,
            "application_outcome": ApplicationOutcome.NOT_APPLIED,
            "execution_readiness": ExecutionReadiness.READY,
            "sync_state": SyncState.PENDING,
        }
        values.update(overrides)
        return OpportunityRecord(**values)

    def test_valid_record_has_no_issues(self):
        self.assertEqual(validate_record(self.make_record()), [])

    def test_missing_lifecycle_is_not_assumed_active(self):
        record = self.make_record(lifecycle_state=LifecycleState.UNKNOWN)
        issues = validate_record(record)
        self.assertIn("LIFECYCLE_UNKNOWN", {issue.code for issue in issues})

    def test_source_presence_does_not_equal_source_verification(self):
        record = self.make_record(
            source_url="https://example.com/jobs/1", source_verified=False
        )
        self.assertEqual(validate_record(record), [])
        self.assertFalse(record.source_verified)

    def test_verification_without_source_is_rejected(self):
        record = self.make_record(source_url=None, source_verified=True)
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


if __name__ == "__main__":
    unittest.main()
