"""Adapters that connect pure assessment functions to the in-memory runner.

Input keys are explicit and missing inputs block the stage. The handlers do not
fetch candidate data, acquire source evidence, persist records, or mutate
external systems.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .assessment import (
    CompensationQuote,
    DuplicateState,
    FitDimensions,
    RankingCandidate,
    RecommendationInputs,
    RequirementCheck,
    VerificationState,
    decide_recommendation,
    evaluate_eligibility,
    rank_candidates,
    resolve_compensation,
    weighted_fit_score,
)
from .domain import EligibilityState
from .pipeline import StageStatus
from .runner import StageExecution


def _blocked(reason: str) -> StageExecution:
    return StageExecution(StageStatus.BLOCKED, {}, reason=reason)


def build_assessment_handlers() -> dict[str, Any]:
    """Return injectable runner handlers for the five pure assessment stages."""

    def eligibility(context: Mapping[str, Any]) -> StageExecution:
        if "requirement_checks" not in context:
            return _blocked("REQUIREMENT_CHECKS_MISSING")
        checks = context["requirement_checks"]
        if not isinstance(checks, (tuple, list)) or any(not isinstance(item, RequirementCheck) for item in checks):
            return _blocked("REQUIREMENT_CHECKS_INVALID")
        return StageExecution(
            StageStatus.SUCCESS,
            {"eligibility": evaluate_eligibility(checks)},
        )

    def fit_assessment(context: Mapping[str, Any]) -> StageExecution:
        if "fit_dimensions" not in context or "fit_weights" not in context:
            return _blocked("FIT_INPUT_MISSING")
        dimensions = context["fit_dimensions"]
        weights = context["fit_weights"]
        if not isinstance(dimensions, FitDimensions) or not isinstance(weights, (tuple, list)):
            return _blocked("FIT_INPUT_INVALID")
        try:
            score = weighted_fit_score(dimensions, tuple(weights))
        except (TypeError, ValueError):
            return _blocked("FIT_INPUT_INVALID")
        return StageExecution(
            StageStatus.SUCCESS,
            {"fit_score": score, "fit_state": "UNKNOWN" if score is None else "ASSESSED"},
        )

    def compensation_resolution(context: Mapping[str, Any]) -> StageExecution:
        if "compensation_quotes" not in context:
            return _blocked("COMPENSATION_QUOTES_MISSING")
        quotes = context["compensation_quotes"]
        if not isinstance(quotes, Mapping):
            return _blocked("COMPENSATION_QUOTES_INVALID")
        if any(value is not None and not isinstance(value, CompensationQuote) for value in quotes.values()):
            return _blocked("COMPENSATION_QUOTE_INVALID")
        try:
            result = resolve_compensation(
                official=quotes.get("official"),
                institution_table=quotes.get("institution_table"),
                public_benchmark=quotes.get("public_benchmark"),
                estimate=quotes.get("estimate"),
            )
        except (TypeError, ValueError):
            return _blocked("COMPENSATION_INPUT_INVALID")
        return StageExecution(StageStatus.SUCCESS, {"compensation": result})

    def ranking(context: Mapping[str, Any]) -> StageExecution:
        if "ranking_candidates" not in context:
            return _blocked("RANKING_CANDIDATES_MISSING")
        candidates = context["ranking_candidates"]
        if not isinstance(candidates, (tuple, list)) or any(not isinstance(item, RankingCandidate) for item in candidates):
            return _blocked("RANKING_CANDIDATES_INVALID")
        limit = context.get("ranking_limit", 50)
        if not isinstance(limit, int):
            return _blocked("RANKING_LIMIT_INVALID")
        try:
            ranked = rank_candidates(candidates, limit=limit)
        except (TypeError, ValueError):
            return _blocked("RANKING_INPUT_INVALID")
        return StageExecution(StageStatus.SUCCESS, {"ranked_candidates": ranked})

    def recommendation(context: Mapping[str, Any]) -> StageExecution:
        # Derive recommendation inputs from the actual upstream stage outputs.
        # Never trust a separately supplied aggregate that could contradict the
        # eligibility stage or silently bypass a missing verification gate.
        required = (
            "eligibility",
            "source_verification_state",
            "currentness_state",
            "duplicate_state",
            "privacy_review_state",
            "provenance_state",
            "schema_validation_state",
        )
        missing = [key for key in required if key not in context]
        if missing:
            return _blocked("RECOMMENDATION_GATE_MISSING:" + ",".join(missing))

        eligibility_state = context["eligibility"]
        source_state = context["source_verification_state"]
        currentness_state = context["currentness_state"]
        duplicate_state = context["duplicate_state"]
        privacy_state = context["privacy_review_state"]
        provenance_state = context["provenance_state"]
        schema_state = context["schema_validation_state"]

        if not isinstance(eligibility_state, EligibilityState):
            return _blocked("ELIGIBILITY_STATE_INVALID")
        if any(
            not isinstance(value, VerificationState)
            for value in (source_state, privacy_state, provenance_state, schema_state)
        ):
            return _blocked("VERIFICATION_GATE_TYPE_INVALID")
        if not isinstance(duplicate_state, DuplicateState):
            return _blocked("DUPLICATE_STATE_INVALID")
        if not isinstance(currentness_state, str):
            return _blocked("CURRENTNESS_STATE_INVALID")

        value = RecommendationInputs(
            eligibility=eligibility_state,
            source_verification=source_state,
            currentness=currentness_state,
            duplicate_state=duplicate_state,
            privacy_review=privacy_state,
            provenance=provenance_state,
            schema_validation=schema_state,
        )
        return StageExecution(
            StageStatus.SUCCESS,
            {"recommendation": decide_recommendation(value)},
        )

    return {
        "eligibility": eligibility,
        "fit_assessment": fit_assessment,
        "compensation_resolution": compensation_resolution,
        "ranking": ranking,
        "recommendation": recommendation,
    }
