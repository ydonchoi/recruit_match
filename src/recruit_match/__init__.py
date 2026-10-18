"""Verification-first recruitment registry bootstrap package."""

from .domain import (
    ApplicationOutcome,
    ExecutionReadiness,
    LifecycleState,
    OpportunityRecord,
    SyncState,
    ValidationIssue,
    validate_record,
)

__all__ = [
    "ApplicationOutcome",
    "ExecutionReadiness",
    "LifecycleState",
    "OpportunityRecord",
    "SyncState",
    "ValidationIssue",
    "validate_record",
]
