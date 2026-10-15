"""Pure assessment contracts with explicit uncertainty and hard eligibility gates.

No source acquisition, candidate storage, network access, persistence or external
mutation is performed here. Missing measurements remain UNKNOWN/None.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Iterable, Sequence

from .domain import EligibilityState, RecommendationState


class EvidenceDomain(StrEnum):
    CANDIDATE = "CANDIDATE"
    RECRUITMENT = "RECRUITMENT"


class VerificationState(StrEnum):
    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class RequirementStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    PASS = "PASS"
    FAIL = "FAIL"


class DuplicateState(StrEnum):
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"
    RESOLVED = "RESOLVED"


class CompensationTier(StrEnum):
    OFFICIAL = "OFFICIAL"
    INSTITUTION_TABLE = "INSTITUTION_TABLE"
    PUBLIC_BENCHMARK = "PUBLIC_BENCHMARK"
    ESTIMATE = "ESTIMATE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RequirementCheck:
    requirement_id: str
    critical: bool
    status: RequirementStatus
    evidence_domains: tuple[EvidenceDomain, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ValueError("REQUIREMENT_ID_REQUIRED")
        if not isinstance(self.status, RequirementStatus):
            raise ValueError("INVALID_REQUIREMENT_STATUS")
        if any(not isinstance(item, EvidenceDomain) for item in self.evidence_domains):
            raise ValueError("INVALID_EVIDENCE_DOMAIN")


def evaluate_eligibility(requirements: Iterable[RequirementCheck]) -> EligibilityState:
    """Evaluate mandatory requirements; an empty/unresolved set never passes."""
    checks = tuple(requirements)
    critical = tuple(item for item in checks if item.critical)
    if not critical:
        return EligibilityState.UNKNOWN
    if any(item.status is RequirementStatus.FAIL for item in critical):
        return EligibilityState.FAIL
    if any(item.status is RequirementStatus.UNKNOWN for item in critical):
        return EligibilityState.UNKNOWN
    return EligibilityState.PASS


@dataclass(frozen=True, slots=True)
class FitDimensions:
    job_fit: float | None
    career_education_fit: float | None
    preference_fit: float | None
    location_fit: float | None

    def __post_init__(self) -> None:
        for name, value in (
            ("job_fit", self.job_fit),
            ("career_education_fit", self.career_education_fit),
            ("preference_fit", self.preference_fit),
            ("location_fit", self.location_fit),
        ):
            if value is not None and not 0.0 <= value <= 100.0:
                raise ValueError(f"FIT_SCORE_OUT_OF_RANGE:{name}")


def weighted_fit_score(
    dimensions: FitDimensions,
    weights: tuple[float, float, float, float],
) -> float | None:
    """Return a weighted score only when all dimensions and weights are known."""
    values = (
        dimensions.job_fit,
        dimensions.career_education_fit,
        dimensions.preference_fit,
        dimensions.location_fit,
    )
    if any(value is None for value in values):
        return None
    if len(weights) != 4 or any(not isfinite(weight) or weight < 0 for weight in weights) or sum(weights) <= 0:
        raise ValueError("INVALID_FIT_WEIGHTS")
    total_weight = sum(weights)
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


@dataclass(frozen=True, slots=True)
class CompensationEvidence:
    tier: CompensationTier
    amount_or_range: str | None
    source_ref: str | None
    assumptions: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"
    reason: str = ""


def resolve_compensation(
    *,
    official: tuple[str, str] | None = None,
    institution_table: tuple[str, str] | None = None,
    public_benchmark: tuple[str, str] | None = None,
    estimate: tuple[str, str, tuple[str, ...]] | None = None,
) -> CompensationEvidence:
    """Resolve by evidence tier; every accepted value must carry a source ref."""
    if official is not None:
        amount, source_ref = official
        if amount.strip() and source_ref.strip():
            return CompensationEvidence(CompensationTier.OFFICIAL, amount, source_ref, confidence="HIGH")
        return CompensationEvidence(CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN", reason="OFFICIAL_EVIDENCE_INCOMPLETE")
    if institution_table is not None:
        amount, source_ref = institution_table
        if amount.strip() and source_ref.strip():
            return CompensationEvidence(CompensationTier.INSTITUTION_TABLE, amount, source_ref, confidence="HIGH")
        return CompensationEvidence(CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN", reason="INSTITUTION_EVIDENCE_INCOMPLETE")
    if public_benchmark is not None:
        amount, source_ref = public_benchmark
        if amount.strip() and source_ref.strip():
            return CompensationEvidence(CompensationTier.PUBLIC_BENCHMARK, amount, source_ref, confidence="MEDIUM")
        return CompensationEvidence(CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN", reason="BENCHMARK_EVIDENCE_INCOMPLETE")
    if estimate is not None:
        amount, source_ref, assumptions = estimate
        if amount.strip() and source_ref.strip() and assumptions:
            return CompensationEvidence(CompensationTier.ESTIMATE, amount, source_ref, assumptions, "LOW")
        return CompensationEvidence(CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN", reason="ESTIMATE_ASSUMPTIONS_OR_SOURCE_MISSING")
    return CompensationEvidence(CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN", reason="COMPENSATION_NOT_FOUND")


@dataclass(frozen=True, slots=True)
class RecommendationInputs:
    eligibility: EligibilityState
    source_verification: VerificationState
    currentness: str
    duplicate_state: DuplicateState
    privacy_review: VerificationState
    provenance: VerificationState
    schema_validation: VerificationState


def decide_recommendation(value: RecommendationInputs) -> RecommendationState:
    """Only explicit all-green evidence can recommend; UNKNOWN is review, not pass."""
    if value.eligibility is EligibilityState.FAIL:
        return RecommendationState.NOT_RECOMMENDED
    if value.duplicate_state is DuplicateState.CONFLICT:
        return RecommendationState.NOT_RECOMMENDED
    if value.source_verification is VerificationState.FAILED or value.provenance is VerificationState.FAILED:
        return RecommendationState.NOT_RECOMMENDED
    if value.privacy_review is VerificationState.FAILED or value.schema_validation is VerificationState.FAILED:
        return RecommendationState.NOT_RECOMMENDED
    if value.currentness in ("CLOSED", "ARCHIVED", "EXPIRED"):
        return RecommendationState.NOT_RECOMMENDED

    all_explicitly_valid = (
        value.eligibility is EligibilityState.PASS
        and value.source_verification is VerificationState.VERIFIED
        and value.currentness in ("ACTIVE", "URGENT", "CLOSING_SOON")
        and value.duplicate_state is DuplicateState.RESOLVED
        and value.privacy_review is VerificationState.VERIFIED
        and value.provenance is VerificationState.VERIFIED
        and value.schema_validation is VerificationState.VERIFIED
    )
    if all_explicitly_valid:
        return RecommendationState.RECOMMENDED
    return RecommendationState.NEEDS_REVIEW


@dataclass(frozen=True, slots=True)
class RankingCandidate:
    opportunity_id: str
    eligibility: EligibilityState
    job_fit: float | None
    career_education_fit: float | None
    total_score: float | None
    location_priority: int | None


def rank_candidates(candidates: Sequence[RankingCandidate], *, limit: int = 50) -> tuple[RankingCandidate, ...]:
    """Rank only supplied records; never pad and never coerce missing scores to zero."""
    if limit < 0:
        raise ValueError("RANK_LIMIT_MUST_BE_NONNEGATIVE")

    eligibility_order = {
        EligibilityState.PASS: 0,
        EligibilityState.UNKNOWN: 1,
        EligibilityState.FAIL: 2,
    }

    def optional_desc(value: float | None) -> tuple[int, float]:
        return (1, 0.0) if value is None else (0, -value)

    def key(candidate: RankingCandidate) -> tuple:
        return (
            eligibility_order[candidate.eligibility],
            optional_desc(candidate.job_fit),
            optional_desc(candidate.career_education_fit),
            candidate.location_priority is None,
            candidate.location_priority if candidate.location_priority is not None else 0,
            optional_desc(candidate.total_score),
            candidate.opportunity_id,
        )

    return tuple(sorted(candidates, key=key)[:limit])
