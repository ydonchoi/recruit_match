"""Budgeted execution boundary for Search Matrix plans.

The module is provider-neutral. One invocation of the injected search callable
is counted as one tool call. It records plan-vs-execution receipts without
claiming that an external provider is configured or that these contracts have
been runtime-verified.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SearchCallStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED_BUDGET = "SKIPPED_BUDGET"


@dataclass(frozen=True, slots=True)
class SearchQueryPlan:
    ordinal: int
    combination_id: str
    query: str

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("SEARCH_PLAN_ORDINAL_MUST_BE_NONNEGATIVE_INTEGER")
        if not isinstance(self.combination_id, str) or not self.combination_id.strip():
            raise ValueError("SEARCH_COMBINATION_ID_REQUIRED")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("SEARCH_QUERY_REQUIRED")


@dataclass(frozen=True, slots=True)
class SearchCallReceipt:
    ordinal: int
    combination_id: str
    status: SearchCallStatus
    call_attempted: bool
    result_count: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("SEARCH_RECEIPT_ORDINAL_INVALID")
        if not isinstance(self.combination_id, str) or not self.combination_id.strip():
            raise ValueError("SEARCH_RECEIPT_COMBINATION_ID_REQUIRED")
        if not isinstance(self.status, SearchCallStatus):
            raise ValueError("SEARCH_RECEIPT_STATUS_INVALID")
        if not isinstance(self.call_attempted, bool):
            raise ValueError("SEARCH_RECEIPT_ATTEMPT_FLAG_INVALID")
        if not isinstance(self.result_count, int) or isinstance(self.result_count, bool) or self.result_count < 0:
            raise ValueError("SEARCH_RECEIPT_RESULT_COUNT_INVALID")
        if self.status is SearchCallStatus.SKIPPED_BUDGET:
            if self.call_attempted or self.result_count != 0 or self.error_code is not None:
                raise ValueError("SKIPPED_SEARCH_MUST_NOT_CLAIM_CALL_OR_RESULT")
        elif not self.call_attempted:
            raise ValueError("NON_SKIPPED_SEARCH_REQUIRES_CALL_ATTEMPT")
        if self.status is SearchCallStatus.SUCCEEDED and self.error_code is not None:
            raise ValueError("SUCCESS_RECEIPT_CANNOT_HAVE_ERROR")
        if self.status is SearchCallStatus.FAILED and not self.error_code:
            raise ValueError("FAILED_RECEIPT_REQUIRES_SANITIZED_ERROR_CODE")


@dataclass(frozen=True, slots=True)
class SearchExecutionReport:
    max_calls: int
    planned_query_count: int
    attempted_call_count: int
    successful_call_count: int
    failed_call_count: int
    skipped_query_count: int
    receipts: tuple[SearchCallReceipt, ...]

    def __post_init__(self) -> None:
        numeric = (
            self.max_calls, self.planned_query_count, self.attempted_call_count,
            self.successful_call_count, self.failed_call_count, self.skipped_query_count,
        )
        if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in numeric):
            raise ValueError("SEARCH_REPORT_COUNTS_MUST_BE_NONNEGATIVE_INTEGERS")
        if self.max_calls < 1:
            raise ValueError("SEARCH_REPORT_BUDGET_MUST_BE_POSITIVE")
        if not isinstance(self.receipts, tuple) or any(
            not isinstance(item, SearchCallReceipt) for item in self.receipts
        ):
            raise ValueError("SEARCH_REPORT_RECEIPTS_INVALID")
        if len(self.receipts) != self.planned_query_count:
            raise ValueError("SEARCH_REPORT_PLAN_RECEIPT_COUNT_MISMATCH")
        if self.attempted_call_count != self.successful_call_count + self.failed_call_count:
            raise ValueError("SEARCH_REPORT_ATTEMPT_COUNT_MISMATCH")
        if self.attempted_call_count > self.max_calls:
            raise ValueError("SEARCH_REPORT_BUDGET_EXCEEDED")
        if self.skipped_query_count + self.attempted_call_count != self.planned_query_count:
            raise ValueError("SEARCH_REPORT_UNACCOUNTED_PLAN_ITEMS")
        if sum(r.call_attempted for r in self.receipts) != self.attempted_call_count:
            raise ValueError("SEARCH_REPORT_RECEIPT_ATTEMPT_MISMATCH")
        if sum(r.status is SearchCallStatus.SUCCEEDED for r in self.receipts) != self.successful_call_count:
            raise ValueError("SEARCH_REPORT_RECEIPT_SUCCESS_MISMATCH")
        if sum(r.status is SearchCallStatus.FAILED for r in self.receipts) != self.failed_call_count:
            raise ValueError("SEARCH_REPORT_RECEIPT_FAILURE_MISMATCH")
        if sum(r.status is SearchCallStatus.SKIPPED_BUDGET for r in self.receipts) != self.skipped_query_count:
            raise ValueError("SEARCH_REPORT_RECEIPT_SKIP_MISMATCH")
        if len({r.ordinal for r in self.receipts}) != len(self.receipts):
            raise ValueError("SEARCH_REPORT_DUPLICATE_ORDINAL")
        if len({r.combination_id for r in self.receipts}) != len(self.receipts):
            raise ValueError("SEARCH_REPORT_DUPLICATE_COMBINATION")


@dataclass(frozen=True, slots=True)
class SearchExecutionBatch:
    report: SearchExecutionReport
    results_by_ordinal: Mapping[int, tuple[Any, ...]]


SearchCallable = Callable[[str], Sequence[Any]]


def plans_from_combinations(combinations: Sequence[Any]) -> tuple[SearchQueryPlan, ...]:
    """Adapt Search Matrix-like objects exposing combination_id and query.

    This adapter deliberately does not import a provider or a legacy package.
    It bridges the stable planner output shape to the explicit budgeted runner.
    """
    if not isinstance(combinations, Sequence) or isinstance(
        combinations, (str, bytes, bytearray)
    ):
        raise ValueError("SEARCH_COMBINATIONS_MUST_BE_SEQUENCE")
    plans = []
    for ordinal, combination in enumerate(combinations):
        combination_id = getattr(combination, "combination_id", None)
        query = getattr(combination, "query", None)
        try:
            plans.append(SearchQueryPlan(ordinal, combination_id, query))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"INVALID_SEARCH_COMBINATION_AT:{ordinal}") from exc
    if len({p.combination_id for p in plans}) != len(plans):
        raise ValueError("SEARCH_PLAN_DUPLICATE_COMBINATION")
    return tuple(plans)


def execute_search_combinations(
    combinations: Sequence[Any],
    search_callable: SearchCallable,
    *,
    max_calls: int,
) -> SearchExecutionBatch:
    """Convert Search Matrix combinations and execute within a hard call budget."""
    return execute_search_plan(
        plans_from_combinations(combinations),
        search_callable,
        max_calls=max_calls,
    )


def execute_search_plan(
    plans: Sequence[SearchQueryPlan],
    search_callable: SearchCallable,
    *,
    max_calls: int,
) -> SearchExecutionBatch:
    """Execute at most max_calls planned queries and return auditable receipts.

    Each invocation of search_callable counts as exactly one tool call at this
    boundary. Provider-internal retries or nested tool calls must be reported
    by the provider adapter separately; this function cannot infer them.
    Failed calls are recorded with a sanitized error code and do not consume
    additional budget through implicit retries.
    """
    if not isinstance(plans, Sequence) or isinstance(plans, (str, bytes, bytearray)):
        raise ValueError("SEARCH_PLANS_MUST_BE_SEQUENCE")
    plan_items = tuple(plans)
    if any(not isinstance(plan, SearchQueryPlan) for plan in plan_items):
        raise ValueError("SEARCH_PLAN_ITEM_INVALID")
    if len({p.ordinal for p in plan_items}) != len(plan_items):
        raise ValueError("SEARCH_PLAN_DUPLICATE_ORDINAL")
    if len({p.combination_id for p in plan_items}) != len(plan_items):
        raise ValueError("SEARCH_PLAN_DUPLICATE_COMBINATION")
    if not isinstance(search_callable, Callable):
        raise ValueError("SEARCH_CALLABLE_REQUIRED")
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 1:
        raise ValueError("SEARCH_CALL_BUDGET_MUST_BE_POSITIVE_INTEGER")

    receipts: list[SearchCallReceipt] = []
    results_by_ordinal: dict[int, tuple[Any, ...]] = {}
    attempted = succeeded = failed = skipped = 0

    for plan in plan_items:
        if attempted >= max_calls:
            receipts.append(SearchCallReceipt(
                ordinal=plan.ordinal,
                combination_id=plan.combination_id,
                status=SearchCallStatus.SKIPPED_BUDGET,
                call_attempted=False,
            ))
            skipped += 1
            continue

        attempted += 1
        try:
            results = search_callable(plan.query)
        except Exception:
            receipts.append(SearchCallReceipt(
                ordinal=plan.ordinal,
                combination_id=plan.combination_id,
                status=SearchCallStatus.FAILED,
                call_attempted=True,
                error_code="PROVIDER_CALL_FAILED",
            ))
            failed += 1
            continue

        if not isinstance(results, Sequence) or isinstance(
            results, (str, bytes, bytearray, Mapping)
        ):
            receipts.append(SearchCallReceipt(
                ordinal=plan.ordinal,
                combination_id=plan.combination_id,
                status=SearchCallStatus.FAILED,
                call_attempted=True,
                error_code="PROVIDER_RESPONSE_NOT_SEQUENCE",
            ))
            failed += 1
            continue

        result_tuple = tuple(results)

        results_by_ordinal[plan.ordinal] = result_tuple
        receipts.append(SearchCallReceipt(
            ordinal=plan.ordinal,
            combination_id=plan.combination_id,
            status=SearchCallStatus.SUCCEEDED,
            call_attempted=True,
            result_count=len(result_tuple),
        ))
        succeeded += 1

    report = SearchExecutionReport(
        max_calls=max_calls,
        planned_query_count=len(plan_items),
        attempted_call_count=attempted,
        successful_call_count=succeeded,
        failed_call_count=failed,
        skipped_query_count=skipped,
        receipts=tuple(receipts),
    )
    return SearchExecutionBatch(report=report, results_by_ordinal=results_by_ordinal)
