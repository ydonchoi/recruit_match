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
    for item in critical:
        if item.status is RequirementStatus.UNKNOWN:
            return EligibilityState.UNKNOWN
        if (
            not item.evidence_refs
            or any(not isinstance(ref, str) or not ref.strip() for ref in item.evidence_refs)
            or not {EvidenceDomain.CANDIDATE, EvidenceDomain.RECRUITMENT}.issubset(set(item.evidence_domains))
        ):
            return EligibilityState.UNKNOWN
    if any(item.status is RequirementStatus.FAIL for item in critical):
        return EligibilityState.FAIL
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
    if not isfinite(total_weight):
        raise ValueError("INVALID_FIT_WEIGHTS")
    score = sum(value * weight for value, weight in zip(values, weights)) / total_weight
    if not isfinite(score):
        raise ValueError("INVALID_FIT_SCORE")
    return score


@dataclass(frozen=True, slots=True)
class CompensationQuote:
    amount_or_range: str
    source_ref: str
    verification: VerificationState
    assumptions: tuple[str, ...] = ()


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
    official: CompensationQuote | None = None,
    institution_table: CompensationQuote | None = None,
    public_benchmark: CompensationQuote | None = None,
    estimate: CompensationQuote | None = None,
) -> CompensationEvidence:
    """Resolve by evidence tier; every accepted value must carry a source ref."""
    for quote, tier, confidence in (
        (official, CompensationTier.OFFICIAL, "HIGH"),
        (institution_table, CompensationTier.INSTITUTION_TABLE, "HIGH"),
        (public_benchmark, CompensationTier.PUBLIC_BENCHMARK, "MEDIUM"),
        (estimate, CompensationTier.ESTIMATE, "LOW"),
    ):
        if quote is None:
            continue
        if not isinstance(quote, CompensationQuote):
            return CompensationEvidence(
                CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN",
                reason=f"COMPENSATION_QUOTE_INVALID:{tier.value}",
            )
        if quote.verification is not VerificationState.VERIFIED:
            return CompensationEvidence(
                CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN",
                reason=f"COMPENSATION_SOURCE_NOT_VERIFIED:{tier.value}",
            )
        if (
            not isinstance(quote.amount_or_range, str)
            or not quote.amount_or_range.strip()
            or not isinstance(quote.source_ref, str)
            or not quote.source_ref.strip()
        ):
            return CompensationEvidence(
                CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN",
                reason=f"COMPENSATION_EVIDENCE_INCOMPLETE:{tier.value}",
            )
        if tier is CompensationTier.ESTIMATE and not quote.assumptions:
            return CompensationEvidence(
                CompensationTier.UNKNOWN, None, None, confidence="UNKNOWN",
                reason="ESTIMATE_ASSUMPTIONS_MISSING",
            )
        return CompensationEvidence(
            tier, quote.amount_or_range, quote.source_ref, quote.assumptions, confidence
        )
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

    def __post_init__(self) -> None:
        if not isinstance(self.opportunity_id, str) or not self.opportunity_id.strip():
            raise ValueError("OPPORTUNITY_ID_REQUIRED")
        if not isinstance(self.eligibility, EligibilityState):
            raise ValueError("INVALID_ELIGIBILITY_STATE")
        for name, value in (("job_fit", self.job_fit), ("career_education_fit", self.career_education_fit)):
            if value is not None and (not isfinite(value) or not 0.0 <= value <= 100.0):
                raise ValueError(f"INVALID_RANKING_DIMENSION:{name}")
        if self.total_score is not None and not isfinite(self.total_score):
            raise ValueError("INVALID_TOTAL_SCORE")


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

    # A failed mandatory gate is a hard exclusion, not merely a low ranking.
    eligible_for_ranking = tuple(
        candidate for candidate in candidates
        if candidate.eligibility is not EligibilityState.FAIL
    )
    return tuple(sorted(eligible_for_ranking, key=key)[:limit])
