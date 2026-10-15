"""Provisional domain contracts; independent of Notion/GitHub schemas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


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

    if not isinstance(record, OpportunityRecord):
        return [ValidationIssue(
            code="INVALID_RECORD_TYPE",
            field="record",
            message="record must be an OpportunityRecord",
        )]

    issues: list[ValidationIssue] = []
    required_text = {
        "registry_id": record.registry_id,
        "opportunity_id": record.opportunity_id,
        "organization": record.organization,
        "position": record.position,
    }
    for field, value in required_text.items():
        if not isinstance(value, str) or not value.strip():
            issues.append(
                ValidationIssue(
                    code="REQUIRED_FIELD_MISSING",
                    field=field,
                    message=f"{field} must be a non-empty string",
                )
            )

    for field in ("recruitment_cycle", "posting_id"):
        value = getattr(record, field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            issues.append(ValidationIssue(
                code="INVALID_OPTIONAL_TEXT",
                field=field,
                message=f"{field} must be None or a non-empty string",
            ))

    enum_fields = {
        "source_verification": (record.source_verification, SourceVerificationState),
        "currentness": (record.currentness, CurrentnessState),
        "lifecycle_state": (record.lifecycle_state, LifecycleState),
        "eligibility": (record.eligibility, EligibilityState),
        "recommendation": (record.recommendation, RecommendationState),
        "application_outcome": (record.application_outcome, ApplicationOutcome),
        "execution_readiness": (record.execution_readiness, ExecutionReadiness),
    }
    for field, (value, expected_type) in enum_fields.items():
        if not isinstance(value, expected_type):
            issues.append(
                ValidationIssue(
                    code="INVALID_ENUM_VALUE",
                    field=field,
                    message=f"{field} must use {expected_type.__name__}",
                )
            )

    if record.source_url is not None:
        try:
            parsed = urlsplit(record.source_url)
            valid_https = (
                parsed.scheme.lower() == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
            )
        except (AttributeError, TypeError, ValueError):
            valid_https = False
        if not valid_https:
            issues.append(
                ValidationIssue(
                    code="SOURCE_URL_NOT_HTTPS",
                    field="source_url",
                    message="source_url must be a valid HTTPS URL",
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
