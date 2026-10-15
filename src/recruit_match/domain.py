"""Provisional domain contracts; independent of Notion/GitHub schemas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LifecycleState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    ON_HOLD = "ON_HOLD"


class CurrentnessState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    URGENT = "URGENT"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class SourceVerificationState(StrEnum):
    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class EligibilityState(StrEnum):
    UNKNOWN = "UNKNOWN"
    PASS = "PASS"
    FAIL = "FAIL"


class RecommendationState(StrEnum):
    UNKNOWN = "UNKNOWN"
    RECOMMENDED = "RECOMMENDED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class ApplicationOutcome(StrEnum):
    UNKNOWN = "UNKNOWN"
    NOT_APPLIED = "NOT_APPLIED"
    APPLIED = "APPLIED"
    INTERVIEWING = "INTERVIEWING"
    OFFERED = "OFFERED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ExecutionReadiness(StrEnum):
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    READY = "READY"


@dataclass(frozen=True, slots=True)
class OpportunityRecord:
    """Provisional opportunity domain record; contains no candidate profile data."""

    registry_id: str
    opportunity_id: str
    organization: str
    position: str
    recruitment_cycle: str | None = None
    posting_id: str | None = None
    source_url: str | None = None
    source_verification: SourceVerificationState = SourceVerificationState.UNKNOWN
    currentness: CurrentnessState = CurrentnessState.UNKNOWN
    lifecycle_state: LifecycleState = LifecycleState.UNKNOWN
    eligibility: EligibilityState = EligibilityState.UNKNOWN
    recommendation: RecommendationState = RecommendationState.UNKNOWN
    application_outcome: ApplicationOutcome = ApplicationOutcome.UNKNOWN
    execution_readiness: ExecutionReadiness = ExecutionReadiness.UNKNOWN


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    field: str
    message: str


def validate_record(record: OpportunityRecord) -> list[ValidationIssue]:
    """Return all detected issues; never infer validity from field presence alone."""

    issues: list[ValidationIssue] = []
    required_text = {
        "registry_id": record.registry_id,
        "opportunity_id": record.opportunity_id,
        "organization": record.organization,
        "position": record.position,
    }
    for field, value in required_text.items():
        if not value.strip():
            issues.append(
                ValidationIssue(
                    code="REQUIRED_FIELD_MISSING",
                    field=field,
                    message=f"{field} must be a non-empty string",
                )
            )

    if record.source_verification is SourceVerificationState.VERIFIED and not record.source_url:
        issues.append(
            ValidationIssue(
                code="SOURCE_VERIFICATION_WITHOUT_SOURCE",
                field="source_url",
                message="source verification cannot be VERIFIED when source_url is absent",
            )
        )

    if record.lifecycle_state is LifecycleState.UNKNOWN:
        issues.append(
            ValidationIssue(
                code="LIFECYCLE_UNKNOWN",
                field="lifecycle_state",
                message="lifecycle state requires explicit classification",
            )
        )

    return issues
