"""Small, explicit domain model. Unknown values are represented, never promoted."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LifecycleState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    ON_HOLD = "ON_HOLD"


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


class SyncState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


@dataclass(frozen=True, slots=True)
class OpportunityRecord:
    """Domain record independent of any persistence or Notion schema."""

    registry_id: str
    opportunity_id: str
    organization: str
    position: str
    source_url: str | None = None
    source_verified: bool = False
    lifecycle_state: LifecycleState = LifecycleState.UNKNOWN
    application_outcome: ApplicationOutcome = ApplicationOutcome.UNKNOWN
    execution_readiness: ExecutionReadiness = ExecutionReadiness.UNKNOWN
    sync_state: SyncState = SyncState.NOT_CONFIGURED


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

    if record.source_verified and not record.source_url:
        issues.append(
            ValidationIssue(
                code="SOURCE_VERIFICATION_WITHOUT_SOURCE",
                field="source_url",
                message="source_verified cannot be true when source_url is absent",
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
