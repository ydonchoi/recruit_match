"""Direct, budgeted ToolCall execution for the Search Matrix discovery stage.

This adapter dispatches one explicitly planned host tool call at a time. The
host dispatcher is injected, the tool name must be allowlisted, retries are
not performed here, and each dispatch attempt consumes one unit of budget.
A returned dispatcher result confirms that the host call returned; an exception
leaves the external execution outcome unknown and is not retried automatically.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Any

from .pipeline import StageStatus
from .runner import StageExecution
from .search_stage import (
    SearchProviderHit,
    _now,
    build_search_plan_handler,
)


class ToolDispatchStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED_BUDGET = "SKIPPED_BUDGET"


class ToolExecutionConfirmation(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class ToolResponseValidation(StrEnum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True, slots=True)
class ToolCallPlan:
    ordinal: int
    call_id: str
    combination_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    query_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("TOOL_CALL_ORDINAL_INVALID")
        for name, value in (
            ("TOOL_CALL_ID_REQUIRED", self.call_id),
            ("TOOL_CALL_COMBINATION_ID_REQUIRED", self.combination_id),
            ("TOOL_CALL_TOOL_NAME_REQUIRED", self.tool_name),
            ("TOOL_CALL_QUERY_HASH_REQUIRED", self.query_sha256),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        if (
            len(self.query_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.query_sha256)
        ):
            raise ValueError("TOOL_CALL_QUERY_HASH_INVALID")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("TOOL_CALL_ARGUMENTS_MUST_BE_MAPPING")
        if any(not isinstance(key, str) or not key.strip() for key in self.arguments):
            raise ValueError("TOOL_CALL_ARGUMENT_KEYS_MUST_BE_STRINGS")
        query = self.arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("TOOL_CALL_QUERY_REQUIRED")
        expected_query_hash = sha256(query.encode("utf-8")).hexdigest()
        if self.query_sha256 != expected_query_hash:
            raise ValueError("TOOL_CALL_QUERY_HASH_MISMATCH")


@dataclass(frozen=True, slots=True)
class ToolCallReceipt:
    ordinal: int
    call_id: str
    combination_id: str
    tool_name: str
    status: ToolDispatchStatus
    dispatch_attempted: bool
    execution_confirmation: ToolExecutionConfirmation
    response_validation: ToolResponseValidation
    started_at: str | None
    finished_at: str | None
    result_count: int
    result_refs: tuple[str, ...]
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("TOOL_RECEIPT_ORDINAL_INVALID")
        if not all(isinstance(value, str) and value.strip() for value in (
            self.call_id, self.combination_id, self.tool_name,
        )):
            raise ValueError("TOOL_RECEIPT_IDENTITY_REQUIRED")
        if not isinstance(self.status, ToolDispatchStatus):
            raise ValueError("TOOL_RECEIPT_STATUS_INVALID")
        if not isinstance(self.dispatch_attempted, bool):
            raise ValueError("TOOL_RECEIPT_ATTEMPT_FLAG_INVALID")
        if not isinstance(self.execution_confirmation, ToolExecutionConfirmation):
            raise ValueError("TOOL_RECEIPT_CONFIRMATION_INVALID")
        if not isinstance(self.response_validation, ToolResponseValidation):
            raise ValueError("TOOL_RECEIPT_RESPONSE_VALIDATION_INVALID")
        if not isinstance(self.result_count, int) or isinstance(self.result_count, bool) or self.result_count < 0:
            raise ValueError("TOOL_RECEIPT_RESULT_COUNT_INVALID")
        if not isinstance(self.result_refs, tuple) or any(not isinstance(ref, str) or not ref.strip() for ref in self.result_refs):
            raise ValueError("TOOL_RECEIPT_RESULT_REFS_INVALID")
        if self.result_count != len(self.result_refs):
            raise ValueError("TOOL_RECEIPT_RESULT_REF_COUNT_MISMATCH")
        if self.status is ToolDispatchStatus.SKIPPED_BUDGET:
            if self.dispatch_attempted or self.execution_confirmation is not ToolExecutionConfirmation.NOT_ATTEMPTED:
                raise ValueError("SKIPPED_TOOL_CALL_CANNOT_BE_ATTEMPTED")
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("SKIPPED_TOOL_CALL_CANNOT_HAVE_TIMESTAMPS")
        elif not self.dispatch_attempted:
            raise ValueError("ATTEMPTED_TOOL_STATUS_REQUIRES_ATTEMPT_FLAG")
        if self.status is ToolDispatchStatus.SUCCEEDED and self.execution_confirmation is not ToolExecutionConfirmation.CONFIRMED:
            raise ValueError("RETURNED_TOOL_CALL_MUST_BE_CONFIRMED")
        if self.status is ToolDispatchStatus.FAILED and self.execution_confirmation is not ToolExecutionConfirmation.UNKNOWN:
            raise ValueError("FAILED_DISPATCH_EXECUTION_MUST_REMAIN_UNKNOWN")
        if self.status is ToolDispatchStatus.FAILED and not self.error_code:
            raise ValueError("FAILED_TOOL_CALL_REQUIRES_SANITIZED_ERROR")
        if self.status is ToolDispatchStatus.SKIPPED_BUDGET and self.error_code is not None:
            raise ValueError("SKIPPED_TOOL_CALL_CANNOT_HAVE_ERROR")
        if self.response_validation is ToolResponseValidation.VALIDATED and self.status is not ToolDispatchStatus.SUCCEEDED:
            raise ValueError("UNSUCCESSFUL_TOOL_CALL_CANNOT_HAVE_VALIDATED_RESPONSE")
        if self.response_validation is ToolResponseValidation.REJECTED and self.status is not ToolDispatchStatus.SUCCEEDED:
            raise ValueError("REJECTED_RESPONSE_REQUIRES_RETURNED_TOOL_CALL")


@dataclass(frozen=True, slots=True)
class ToolCallExecutionReport:
    max_calls: int
    planned_call_count: int
    attempted_dispatch_count: int
    successful_dispatch_count: int
    failed_dispatch_count: int
    skipped_call_count: int
    execution_confirmed_count: int
    response_validated_count: int
    response_rejected_count: int
    receipts: tuple[ToolCallReceipt, ...]

    def __post_init__(self) -> None:
        counts = (
            self.max_calls, self.planned_call_count, self.attempted_dispatch_count,
            self.successful_dispatch_count, self.failed_dispatch_count,
            self.skipped_call_count, self.execution_confirmed_count,
            self.response_validated_count, self.response_rejected_count,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts):
            raise ValueError("TOOL_REPORT_COUNTS_MUST_BE_NONNEGATIVE_INTEGERS")
        if self.max_calls < 1:
            raise ValueError("TOOL_REPORT_BUDGET_MUST_BE_POSITIVE")
        if not isinstance(self.receipts, tuple) or any(not isinstance(r, ToolCallReceipt) for r in self.receipts):
            raise ValueError("TOOL_REPORT_RECEIPTS_INVALID")
        if len(self.receipts) != self.planned_call_count:
            raise ValueError("TOOL_REPORT_PLAN_RECEIPT_MISMATCH")
        if self.planned_call_count != self.attempted_dispatch_count + self.skipped_call_count:
            raise ValueError("TOOL_REPORT_PLAN_ACCOUNTING_MISMATCH")
        if self.attempted_dispatch_count != self.successful_dispatch_count + self.failed_dispatch_count:
            raise ValueError("TOOL_REPORT_ATTEMPT_ACCOUNTING_MISMATCH")
        if self.attempted_dispatch_count > self.max_calls:
            raise ValueError("TOOL_REPORT_BUDGET_EXCEEDED")
        if self.execution_confirmed_count != self.successful_dispatch_count:
            raise ValueError("TOOL_REPORT_CONFIRMATION_COUNT_MISMATCH")
        if self.response_validated_count + self.response_rejected_count != self.successful_dispatch_count:
            raise ValueError("TOOL_REPORT_RESPONSE_COUNT_MISMATCH")
        if sum(r.dispatch_attempted for r in self.receipts) != self.attempted_dispatch_count:
            raise ValueError("TOOL_REPORT_RECEIPT_ATTEMPT_MISMATCH")
        if sum(r.status is ToolDispatchStatus.SUCCEEDED for r in self.receipts) != self.successful_dispatch_count:
            raise ValueError("TOOL_REPORT_RECEIPT_SUCCESS_MISMATCH")
        if sum(r.status is ToolDispatchStatus.FAILED for r in self.receipts) != self.failed_dispatch_count:
            raise ValueError("TOOL_REPORT_RECEIPT_FAILURE_MISMATCH")
        if sum(r.status is ToolDispatchStatus.SKIPPED_BUDGET for r in self.receipts) != self.skipped_call_count:
            raise ValueError("TOOL_REPORT_RECEIPT_SKIP_MISMATCH")
        if sum(r.execution_confirmation is ToolExecutionConfirmation.CONFIRMED for r in self.receipts) != self.execution_confirmed_count:
            raise ValueError("TOOL_REPORT_RECEIPT_CONFIRMATION_MISMATCH")
        if sum(r.response_validation is ToolResponseValidation.VALIDATED for r in self.receipts) != self.response_validated_count:
            raise ValueError("TOOL_REPORT_RECEIPT_VALIDATION_MISMATCH")
        if sum(r.response_validation is ToolResponseValidation.REJECTED for r in self.receipts) != self.response_rejected_count:
            raise ValueError("TOOL_REPORT_RECEIPT_REJECTION_MISMATCH")
        if len({r.ordinal for r in self.receipts}) != len(self.receipts):
            raise ValueError("TOOL_REPORT_DUPLICATE_ORDINAL")
        if len({r.call_id for r in self.receipts}) != len(self.receipts):
            raise ValueError("TOOL_REPORT_DUPLICATE_CALL_ID")


@dataclass(frozen=True, slots=True)
class ToolCallExecutionBatch:
    report: ToolCallExecutionReport
    results_by_ordinal: Mapping[int, tuple[SearchProviderHit, ...]]


ToolDispatcher = Callable[[str, Mapping[str, Any]], Any]
ResultNormalizer = Callable[[Any], Sequence[SearchProviderHit]]
ArgumentsBuilder = Callable[[Any], Mapping[str, Any]]


def execute_tool_call_plan(
    plans: Sequence[ToolCallPlan],
    dispatcher: ToolDispatcher,
    result_normalizer: ResultNormalizer,
    *,
    max_calls: int,
    allowed_tool_names: Sequence[str],
    clock: Callable[[], datetime] | None = None,
    run_id: str,
) -> ToolCallExecutionBatch:
    """Dispatch a preplanned sequence without hidden retries or budget expansion.

    The budget counts each call made to the injected host dispatcher. A raised
    exception is an ambiguous external outcome, so it consumes budget and is
    recorded with UNKNOWN execution confirmation rather than retried.
    """
    if not isinstance(plans, Sequence) or isinstance(plans, (str, bytes, bytearray)):
        raise ValueError("TOOL_CALL_PLANS_MUST_BE_SEQUENCE")
    plan_items = tuple(plans)
    if any(not isinstance(plan, ToolCallPlan) for plan in plan_items):
        raise ValueError("TOOL_CALL_PLAN_ITEM_INVALID")
    if not callable(dispatcher):
        raise ValueError("TOOL_DISPATCHER_REQUIRED")
    if not callable(result_normalizer):
        raise ValueError("TOOL_RESULT_NORMALIZER_REQUIRED")
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 1:
        raise ValueError("TOOL_CALL_BUDGET_MUST_BE_POSITIVE_INTEGER")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("TOOL_CALL_RUN_ID_REQUIRED")
    if not isinstance(allowed_tool_names, Sequence) or isinstance(allowed_tool_names, (str, bytes, bytearray)):
        raise ValueError("TOOL_ALLOWLIST_MUST_BE_SEQUENCE")
    allowlist = frozenset(allowed_tool_names)
    if not allowlist or any(not isinstance(name, str) or not name.strip() for name in allowlist):
        raise ValueError("TOOL_ALLOWLIST_INVALID")
    if any(plan.tool_name not in allowlist for plan in plan_items):
        raise ValueError("TOOL_NAME_NOT_ALLOWLISTED")
    if len({p.ordinal for p in plan_items}) != len(plan_items):
        raise ValueError("TOOL_CALL_DUPLICATE_ORDINAL")
    if len({p.call_id for p in plan_items}) != len(plan_items):
        raise ValueError("TOOL_CALL_DUPLICATE_CALL_ID")
    if len({p.combination_id for p in plan_items}) != len(plan_items):
        raise ValueError("TOOL_CALL_DUPLICATE_COMBINATION_ID")
    clock_fn = clock or (lambda: datetime.now(timezone.utc))

    receipts: list[ToolCallReceipt] = []
    results: dict[int, tuple[SearchProviderHit, ...]] = {}
    attempted = succeeded = failed = skipped = validated = rejected = 0

    for plan in plan_items:
        if attempted >= max_calls:
            receipts.append(ToolCallReceipt(
                ordinal=plan.ordinal, call_id=plan.call_id,
                combination_id=plan.combination_id, tool_name=plan.tool_name,
                status=ToolDispatchStatus.SKIPPED_BUDGET, dispatch_attempted=False,
                execution_confirmation=ToolExecutionConfirmation.NOT_ATTEMPTED,
                response_validation=ToolResponseValidation.NOT_RUN,
                started_at=None, finished_at=None, result_count=0, result_refs=(),
            ))
            skipped += 1
            continue

        attempted += 1
        started_at = _now(clock_fn)
        try:
            raw_result = dispatcher(plan.tool_name, deepcopy(dict(plan.arguments)))
        except Exception:
            finished_at = _now(clock_fn)
            receipts.append(ToolCallReceipt(
                ordinal=plan.ordinal, call_id=plan.call_id,
                combination_id=plan.combination_id, tool_name=plan.tool_name,
                status=ToolDispatchStatus.FAILED, dispatch_attempted=True,
                execution_confirmation=ToolExecutionConfirmation.UNKNOWN,
                response_validation=ToolResponseValidation.NOT_RUN,
                started_at=started_at, finished_at=finished_at,
                result_count=0, result_refs=(), error_code="TOOL_DISPATCH_EXCEPTION",
            ))
            failed += 1
            continue

        finished_at = _now(clock_fn)
        succeeded += 1
        try:
            normalized = result_normalizer(raw_result)
            if not isinstance(normalized, Sequence) or isinstance(normalized, (str, bytes, bytearray, Mapping)):
                raise ValueError("NORMALIZER_OUTPUT_NOT_SEQUENCE")
            hits = tuple(normalized)
            for hit in hits:
                if not isinstance(hit, SearchProviderHit):
                    raise ValueError("NORMALIZER_RESULT_INVALID")
                hit.__post_init__()
        except Exception:
            receipts.append(ToolCallReceipt(
                ordinal=plan.ordinal, call_id=plan.call_id,
                combination_id=plan.combination_id, tool_name=plan.tool_name,
                status=ToolDispatchStatus.SUCCEEDED, dispatch_attempted=True,
                execution_confirmation=ToolExecutionConfirmation.CONFIRMED,
                response_validation=ToolResponseValidation.REJECTED,
                started_at=started_at, finished_at=finished_at,
                result_count=0, result_refs=(), error_code="TOOL_RESPONSE_NORMALIZATION_FAILED",
            ))
            rejected += 1
            continue

        validated += 1
        result_refs = tuple(
            f"tool-result:{run_id}:{plan.combination_id}:{index}"
            for index, _ in enumerate(hits)
        )
        results[plan.ordinal] = hits
        receipts.append(ToolCallReceipt(
            ordinal=plan.ordinal, call_id=plan.call_id,
            combination_id=plan.combination_id, tool_name=plan.tool_name,
            status=ToolDispatchStatus.SUCCEEDED, dispatch_attempted=True,
            execution_confirmation=ToolExecutionConfirmation.CONFIRMED,
            response_validation=ToolResponseValidation.VALIDATED,
            started_at=started_at, finished_at=finished_at,
            result_count=len(hits), result_refs=result_refs,
        ))

    report = ToolCallExecutionReport(
        max_calls=max_calls,
        planned_call_count=len(plan_items),
        attempted_dispatch_count=attempted,
        successful_dispatch_count=succeeded,
        failed_dispatch_count=failed,
        skipped_call_count=skipped,
        execution_confirmed_count=succeeded,
        response_validated_count=validated,
        response_rejected_count=rejected,
        receipts=tuple(receipts),
    )
    return ToolCallExecutionBatch(report=report, results_by_ordinal=results)


def build_tool_call_search_handlers(
    *,
    run_id: str,
    planner: Callable[[Mapping[str, Any]], Sequence[Any]],
    dispatcher: ToolDispatcher,
    result_normalizer: ResultNormalizer,
    tool_name: str,
    allowed_tool_names: Sequence[str],
    max_planned_combinations: int,
    max_calls: int,
    arguments_builder: ArgumentsBuilder | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Callable[[Mapping[str, Any]], StageExecution]]:
    """Compose a Search Matrix plan handler with direct host ToolCall dispatch."""
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("TOOL_NAME_REQUIRED")
    allowlist = frozenset(allowed_tool_names)
    if tool_name not in allowlist:
        raise ValueError("TOOL_NAME_NOT_ALLOWLISTED")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("TOOL_CALL_RUN_ID_REQUIRED")

    def default_arguments(combination: Any) -> Mapping[str, Any]:
        args: dict[str, Any] = {"query": getattr(combination, "query")}
        axis = getattr(combination, "job_axis", None)
        org_type = getattr(combination, "organization_type", None)
        if isinstance(axis, str) and axis:
            args["search_axis"] = axis
        if isinstance(org_type, str) and org_type:
            args["organization_type"] = org_type
        return args

    build_args = arguments_builder or default_arguments

    def discovery(context: Mapping[str, Any]) -> StageExecution:
        combinations = context.get("search_combinations")
        if not isinstance(combinations, Sequence) or isinstance(combinations, (str, bytes, bytearray)) or not combinations:
            return StageExecution(StageStatus.BLOCKED, {}, reason="SEARCH_COMBINATIONS_MISSING")
        from .search_execution import plans_from_combinations
        try:
            search_plans = plans_from_combinations(combinations)
            tool_plans = tuple(
                ToolCallPlan(
                    ordinal=plan.ordinal,
                    call_id=f"{run_id}:{plan.combination_id}:{tool_name}",
                    combination_id=plan.combination_id,
                    tool_name=tool_name,
                    arguments=deepcopy(dict(build_args(combinations[plan.ordinal]))),
                    query_sha256=sha256(plan.query.encode("utf-8")).hexdigest(),
                )
                for plan in search_plans
            )
        except Exception:
            return StageExecution(StageStatus.BLOCKED, {}, reason="TOOL_CALL_PLAN_INVALID")

        batch = execute_tool_call_plan(
            tool_plans, dispatcher, result_normalizer,
            max_calls=max_calls, allowed_tool_names=allowed_tool_names,
            clock=clock, run_id=run_id,
        )
        discovered: list[dict[str, Any]] = []
        search_receipts: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        for plan, receipt in zip(search_plans, batch.report.receipts):
            result_refs: list[str] = []
            for hit in batch.results_by_ordinal.get(plan.ordinal, ()):
                result_ref = f"search-result:{run_id}:{plan.combination_id}:{len(result_refs)}"
                result_refs.append(result_ref)
                discovered.append({
                    "provider_id": tool_name,
                    "combination_id": plan.combination_id,
                    "provider_result_id": hit.provider_result_id,
                    "title": hit.title,
                    "source_url": hit.source_url,
                    "observed_at": receipt.finished_at or "",
                    "query_sha256": plan.query_sha256 if hasattr(plan, "query_sha256") else sha256(plan.query.encode("utf-8")).hexdigest(),
                    "result_ref": result_ref,
                })
            search_receipts.append({
                "run_id": run_id,
                "provider_id": tool_name,
                "combination_id": plan.combination_id,
                "query_sha256": sha256(plan.query.encode("utf-8")).hexdigest(),
                "status": receipt.status.value,
                "call_attempted": receipt.dispatch_attempted,
                "started_at": receipt.started_at,
                "finished_at": receipt.finished_at,
                "result_count": receipt.result_count,
                "result_refs": tuple(result_refs),
                "error_code": receipt.error_code,
                "tool_call_id": receipt.call_id,
                "execution_confirmation": receipt.execution_confirmation.value,
                "response_validation": receipt.response_validation.value,
            })
            if receipt.dispatch_attempted:
                evidence_refs.append(f"tool-call-receipt:{run_id}:{receipt.call_id}")

        report = batch.report
        complete = (
            report.failed_dispatch_count == 0
            and report.skipped_call_count == 0
            and report.response_rejected_count == 0
            and report.successful_dispatch_count == report.planned_call_count
        )
        output = {
            "search_provider_id": tool_name,
            "tool_call_execution_report": report,
            "tool_call_receipts": report.receipts,
            "search_execution_report": report,
            "search_invocation_receipts": tuple(search_receipts),
            "discovered_search_results": tuple(discovered),
            "discovery_complete": complete,
            "discovery_state": "COMPLETE" if complete else "PARTIAL",
        }
        if report.successful_dispatch_count == 0:
            return StageExecution(StageStatus.FAILED, output, evidence_refs=tuple(evidence_refs), reason="NO_TOOL_CALL_SUCCEEDED")
        if not complete:
            return StageExecution(StageStatus.BLOCKED, output, evidence_refs=tuple(evidence_refs), reason="TOOL_CALL_PLAN_NOT_FULLY_EXECUTED")
        return StageExecution(
            StageStatus.SUCCESS, output,
            output_refs=tuple(item["result_ref"] for item in discovered),
            evidence_refs=tuple(evidence_refs),
        )

    return {
        "search_plan": build_search_plan_handler(planner, max_planned_combinations=max_planned_combinations),
        "discovery": discovery,
    }
