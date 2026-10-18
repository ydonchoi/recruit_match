"""Pipeline-stage adapters for Search Matrix planning and discovery.

The planner and provider are injected explicitly. This module does not select a
provider, fetch credentials, or perform application submissions.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from .pipeline import StageStatus
from .runner import StageExecution
from .search_execution import (
    SearchCallStatus,
    SearchExecutionBatch,
    execute_search_combinations,
    plans_from_combinations,
)


@dataclass(frozen=True, slots=True)
class SearchProviderHit:
    provider_result_id: str
    title: str
    source_url: str

    def __post_init__(self) -> None:
        for name, value in (
            ("SEARCH_PROVIDER_RESULT_ID_REQUIRED", self.provider_result_id),
            ("SEARCH_RESULT_TITLE_REQUIRED", self.title),
            ("SEARCH_RESULT_URL_REQUIRED", self.source_url),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        parsed = urlsplit(self.source_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("SEARCH_RESULT_URL_INVALID")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("SEARCH_RESULT_URL_CREDENTIALS_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class DiscoveredSearchResult:
    provider_id: str
    combination_id: str
    provider_result_id: str
    title: str
    source_url: str
    observed_at: str
    query_sha256: str
    result_ref: str


@dataclass(frozen=True, slots=True)
class SearchInvocationReceipt:
    run_id: str
    provider_id: str
    combination_id: str
    query_sha256: str
    status: SearchCallStatus
    call_attempted: bool
    started_at: str | None
    finished_at: str | None
    result_count: int
    result_refs: tuple[str, ...]
    error_code: str | None = None


def _now(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SEARCH_CLOCK_MUST_RETURN_AWARE_DATETIME")
    return value.astimezone(timezone.utc).isoformat()


def _unwrap_combination(value: Any) -> Any:
    nested = getattr(value, "combination", None)
    return nested if nested is not None else value


def build_adaptive_planner_callback(
    adaptive_planner: Any,
    candidate_evidence_provider: Any,
    *,
    query_key: str = "user_query",
) -> Callable[[Mapping[str, Any]], Sequence[Any]]:
    """Adapt the legacy-style AdaptiveSearchPlanner.plan(evidence, query) API.

    The candidate evidence provider and adaptive planner are injected. The
    request-scope stage must place the user query under query_key. This adapter
    does not load candidate records itself or persist learned search memory.
    """
    plan_method = getattr(adaptive_planner, "plan", None)
    evidence_method = getattr(candidate_evidence_provider, "get", None)
    if not callable(plan_method):
        raise ValueError("ADAPTIVE_SEARCH_PLANNER_REQUIRED")
    if not callable(evidence_method):
        raise ValueError("CANDIDATE_EVIDENCE_PROVIDER_REQUIRED")
    if not isinstance(query_key, str) or not query_key.strip():
        raise ValueError("USER_QUERY_CONTEXT_KEY_REQUIRED")

    def planner(context: Mapping[str, Any]) -> Sequence[Any]:
        if not isinstance(context, Mapping):
            raise ValueError("SEARCH_PLANNER_CONTEXT_REQUIRED")
        query = context.get(query_key, "")
        if not isinstance(query, str):
            raise ValueError("USER_QUERY_MUST_BE_STRING")
        evidence = evidence_method()
        if evidence is None:
            raise ValueError("CANDIDATE_EVIDENCE_UNAVAILABLE")
        plans = plan_method(evidence, query)
        if not isinstance(plans, Sequence) or isinstance(plans, (str, bytes, bytearray)):
            raise ValueError("ADAPTIVE_PLANNER_OUTPUT_MUST_BE_SEQUENCE")
        return tuple(plans)

    return planner


def build_search_plan_handler(
    planner: Callable[[Mapping[str, Any]], Sequence[Any]],
    *,
    max_planned_combinations: int,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    if not callable(planner):
        raise ValueError("SEARCH_PLANNER_REQUIRED")
    if not isinstance(max_planned_combinations, int) or isinstance(max_planned_combinations, bool) or max_planned_combinations < 1:
        raise ValueError("MAX_PLANNED_COMBINATIONS_MUST_BE_POSITIVE_INTEGER")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        try:
            proposed = planner(context)
            if not isinstance(proposed, Sequence) or isinstance(proposed, (str, bytes, bytearray)):
                return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_PLANNER_OUTPUT_INVALID")
            combinations = tuple(_unwrap_combination(item) for item in proposed)
            if not combinations:
                return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_PLAN_EMPTY")
            if len(combinations) > max_planned_combinations:
                return StageExecution(
                    StageStatus.BLOCKED,
                    {"search_plan_count": len(combinations), "search_plan_limit": max_planned_combinations},
                    reason="SEARCH_PLAN_EXCEEDS_MAX_COMBINATIONS",
                )
            plans = plans_from_combinations(combinations)
        except Exception:
            return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_PLAN_INVALID")

        return StageExecution(
            StageStatus.SUCCESS,
            {
                "search_combinations": combinations,
                "search_plan_count": len(plans),
                "search_plan_combination_ids": tuple(plan.combination_id for plan in plans),
            },
        )

    return handler


def build_search_discovery_handler(
    *,
    run_id: str,
    provider_id: str,
    search_callable: Callable[[str], Sequence[SearchProviderHit]],
    max_calls: int,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("SEARCH_RUN_ID_REQUIRED")
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValueError("SEARCH_PROVIDER_ID_REQUIRED")
    if not callable(search_callable):
        raise ValueError("SEARCH_CALLABLE_REQUIRED")
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 1:
        raise ValueError("SEARCH_CALL_BUDGET_MUST_BE_POSITIVE_INTEGER")
    clock_fn = clock or (lambda: datetime.now(timezone.utc))

    def handler(context: Mapping[str, Any]) -> StageExecution:
        combinations = context.get("search_combinations")
        if not isinstance(combinations, Sequence) or isinstance(combinations, (str, bytes, bytearray)) or not combinations:
            return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_COMBINATIONS_MISSING")
        try:
            plans = plans_from_combinations(combinations)
        except (TypeError, ValueError):
            return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_PLAN_INVALID")

        timings: list[tuple[str, str]] = []

        def measured_call(query: str) -> Sequence[SearchProviderHit]:
            started = _now(clock_fn)
            try:
                hits = search_callable(query)
                if not isinstance(hits, Sequence) or isinstance(hits, (str, bytes, bytearray, Mapping)):
                    raise ValueError("PROVIDER_RESPONSE_NOT_SEQUENCE")
                normalized = tuple(hits)
                for hit in normalized:
                    if not isinstance(hit, SearchProviderHit):
                        raise ValueError("PROVIDER_RESULT_SHAPE_INVALID")
                    hit.__post_init__()
            except Exception:
                timings.append((started, _now(clock_fn)))
                raise
            timings.append((started, _now(clock_fn)))
            return normalized

        batch: SearchExecutionBatch = execute_search_combinations(
            combinations, measured_call, max_calls=max_calls
        )
        timing_index = 0
        discovered: list[DiscoveredSearchResult] = []
        receipts: list[SearchInvocationReceipt] = []
        evidence_refs: list[str] = []
        query_by_id = {plan.combination_id: plan.query for plan in plans}

        for receipt in batch.report.receipts:
            query = query_by_id[receipt.combination_id]
            query_hash = sha256(query.encode("utf-8")).hexdigest()
            if receipt.call_attempted:
                started_at, finished_at = timings[timing_index]
                timing_index += 1
            else:
                started_at, finished_at = None, None

            result_refs: list[str] = []
            hits = batch.results_by_ordinal.get(receipt.ordinal, ())
            for result_index, hit in enumerate(hits):
                result_ref = f"search-result:{run_id}:{receipt.combination_id}:{result_index}"
                result_refs.append(result_ref)
                discovered.append(DiscoveredSearchResult(
                    provider_id=provider_id,
                    combination_id=receipt.combination_id,
                    provider_result_id=hit.provider_result_id,
                    title=hit.title,
                    source_url=hit.source_url,
                    observed_at=finished_at or "",
                    query_sha256=query_hash,
                    result_ref=result_ref,
                ))

            receipts.append(SearchInvocationReceipt(
                run_id=run_id,
                provider_id=provider_id,
                combination_id=receipt.combination_id,
                query_sha256=query_hash,
                status=receipt.status,
                call_attempted=receipt.call_attempted,
                started_at=started_at,
                finished_at=finished_at,
                result_count=receipt.result_count,
                result_refs=tuple(result_refs),
                error_code=receipt.error_code,
            ))
            if receipt.call_attempted:
                evidence_refs.append(
                    f"search-invocation:{run_id}:{provider_id}:{receipt.combination_id}"
                )

        report = batch.report
        complete = (
            report.failed_call_count == 0
            and report.skipped_query_count == 0
            and report.successful_call_count == report.planned_query_count
        )
        output = {
            "search_provider_id": provider_id,
            "search_execution_report": report,
            "search_invocation_receipts": tuple(receipts),
            "discovered_search_results": tuple(discovered),
            "discovery_complete": complete,
            "discovery_state": "COMPLETE" if complete else "PARTIAL",
        }
        if report.successful_call_count == 0:
            return StageExecution(
                StageStatus.FAILED, output, evidence_refs=tuple(evidence_refs),
                reason="NO_SEARCH_CALL_SUCCEEDED",
            )
        if not complete:
            return StageExecution(
                StageStatus.BLOCKED, output, evidence_refs=tuple(evidence_refs),
                reason="SEARCH_PLAN_NOT_FULLY_EXECUTED",
            )
        return StageExecution(
            StageStatus.SUCCESS,
            output,
            output_refs=tuple(result.result_ref for result in discovered),
            evidence_refs=tuple(evidence_refs),
        )

    return handler


def build_search_handlers(
    *,
    run_id: str,
    planner: Callable[[Mapping[str, Any]], Sequence[Any]],
    search_callable: Callable[[str], Sequence[SearchProviderHit]],
    provider_id: str,
    max_planned_combinations: int,
    max_calls: int,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Callable[[Mapping[str, Any]], StageExecution]]:
    """Build concrete handlers for the search_plan and discovery stages."""
    return {
        "search_plan": build_search_plan_handler(
            planner, max_planned_combinations=max_planned_combinations
        ),
        "discovery": build_search_discovery_handler(
            run_id=run_id,
            provider_id=provider_id,
            search_callable=search_callable,
            max_calls=max_calls,
            clock=clock,
        ),
    }
