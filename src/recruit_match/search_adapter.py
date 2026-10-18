"""Adapters connecting Search Matrix planning to the discovery pipeline stage.

No provider is selected by this module. Callers explicitly inject the planner,
provider identity, search callable, call budget, and run ID. Provider results
must be normalized to SearchProviderHit before they can enter the pipeline.
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
)


@dataclass(frozen=True, slots=True)
class SearchProviderHit:
    """A provider-normalized search result, not an official-source verification."""

    provider_result_id: str
    title: str
    source_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_result_id, str) or not self.provider_result_id.strip():
            raise ValueError("SEARCH_PROVIDER_RESULT_ID_REQUIRED")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("SEARCH_RESULT_TITLE_REQUIRED")
        if not isinstance(self.source_url, str) or not self.source_url.strip():
            raise ValueError("SEARCH_RESULT_URL_REQUIRED")
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


def _utc_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime):
        raise ValueError("SEARCH_CLOCK_MUST_RETURN_DATETIME")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SEARCH_CLOCK_MUST_RETURN_TIMEZONE_AWARE_DATETIME")
    return value.astimezone(timezone.utc).isoformat()


def _combination(value: Any) -> Any:
    # Legacy AdaptiveSearchPlanner.plan() returns QueryPlan(combination=...).
    # The direct SearchMatrixPlanner.derive() path returns combinations directly.
    nested = getattr(value, "combination", None)
    return nested if nested is not None else value


def build_search_plan_handler(
    planner: Callable[[Mapping[str, Any]], Sequence[Any]],
    *,
    max_planned_combinations: int,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    """Build the search_plan handler from an explicitly injected planner.

    The planner receives a read-only-by-contract snapshot of pipeline context.
    Oversized plans are blocked rather than silently truncated, preserving
    accurate planned-vs-executed accounting.
    """
    if not callable(planner):
        raise ValueError("SEARCH_PLANNER_REQUIRED")
    if (
        not isinstance(max_planned_combinations, int)
        or isinstance(max_planned_combinations, bool)
        or max_planned_combinations < 1
    ):
        raise ValueError("MAX_PLANNED_COMBINATIONS_MUST_BE_POSITIVE_INTEGER")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        try:
            combinations = planner(context)
            if not isinstance(combinations, Sequence) or isinstance(
                combinations, (str, bytes, bytearray)
            ):
                return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_PLANNER_OUTPUT_INVALID")
            combinations = tuple(_combination(item) for item in combinations)
            if not combinations:
                return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_PLAN_EMPTY")
            if len(combinations) > max_planned_combinations:
                return StageExecution(
                    StageStatus.BLOCKED,
                    {
                        "search_plan_count": len(combinations),
                        "search_plan_limit": max_planned_combinations,
                    },
                    reason="SEARCH_PLAN_EXCEEDS_MAX_COMBINATIONS",
                )
            # Validate shape and stable IDs before exposing the plan to discovery.
            from .search_execution import plans_from_combinations
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
    """Build the discovery stage around an explicit provider and hard call budget.

    A successful invocation means the provider callable returned a valid
    sequence. It does not mean that the result is authoritative, current, or
    suitable for eligibility; those checks belong to later stages.
    """
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
        if not isinstance(combinations, Sequence) or isinstance(
            combinations, (str, bytes, bytearray)
        ):
            return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_COMBINATIONS_MISSING")
        if not combinations:
            return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_PLAN_EMPTY")

        timing: list[tuple[str, str]] = []

        def measured_search(query: str) -> Sequence[SearchProviderHit]:
            started = _utc_timestamp(clock_fn)
            try:
                response = search_callable(query)
                if not isinstance(response, Sequence) or isinstance(
                    response, (str, bytes, bytearray, Mapping)
                ):
                    raise ValueError("PROVIDER_RESPONSE_NOT_SEQUENCE")
                normalized = tuple(response)
                if any(not isinstance(hit, SearchProviderHit) for hit in normalized):
                    raise ValueError("PROVIDER_RESULT_SHAPE_INVALID")
                # Re-run validation to catch malformed instances from unsafe adapters.
                for hit in normalized:
                    hit.__post_init__()
            except Exception:
                finished = _utc_timestamp(clock_fn)
                timing.append((started, finished))
                raise
            finished = _utc_timestamp(clock_fn)
            timing.append((started, finished))
            return normalized

        batch: SearchExecutionBatch = execute_search_combinations(
            combinations, measured_search, max_calls=max_calls
        )
        discovered: list[DiscoveredSearchResult] = []
        invocation_receipts: list[SearchInvocationReceipt] = []
        evidence_refs: list[str] = []

        for index, receipt in enumerate(batch.report.receipts):
            query = next(
                getattr(_combination(item), "query")
                for item in combinations
                if getattr(_combination(item), "combination_id") == receipt.combination_id
            )
            query_hash = sha256(query.encode("utf-8")).hexdigest()
            times = timing[index] if receipt.call_attempted and index < len(timing) else (None, None)
            observed_at = times[1]
            result_refs: list[str] = []
            result_items = batch.results_by_ordinal.get(receipt.ordinal, ())
            for hit_index, hit in enumerate(result_items):
                result_ref = (
                    f"search-result:{run_id}:{receipt.combination_id}:{hit_index}"
                )
                result_refs.append(result_ref)
                discovered.append(DiscoveredSearchResult(
                    provider_id=provider_id,
                    combination_id=receipt.combination_id,
                    provider_result_id=hit.provider_result_id,
                    title=hit.title,
                    source_url=hit.source_url,
                    observed_at=observed_at or "",
                    query_sha256=query_hash,
                ))
            invocation_receipts.append(SearchInvocationReceipt(
                run_id=run_id,
                provider_id=provider_id,
                combination_id=receipt.combination_id,
                query_sha256=query_hash,
                status=receipt.status,
                call_attempted=receipt.call_attempted,
                started_at=times[0],
                finished_at=times[1],
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
            "search_invocation_receipts": tuple(invocation_receipts),
            "discovered_search_results": tuple(discovered),
            "discovery_complete": complete,
            "discovery_state": "COMPLETE" if complete else "PARTIAL",
        }
        if report.successful_call_count == 0:
            return StageExecution(
                StageStatus.FAILED,
                output,
                evidence_refs=tuple(evidence_refs),
                reason="NO_SEARCH_CALL_SUCCEEDED",
            )
        if not complete:
            return StageExecution(
                StageStatus.BLOCKED,
                output,
                evidence_refs=tuple(evidence_refs),
                reason="SEARCH_PLAN_NOT_FULLY_EXECUTED",
            )
        return StageExecution(
            StageStatus.SUCCESS,
            output,
            output_refs=tuple(
                f"search-result:{run_id}:{item.combination_id}:{index}"
                for item in invocation_receipts
                for index in range(item.result_count)
            ),
            evidence_refs=tuple(evidence_refs),
        )

    return handler
