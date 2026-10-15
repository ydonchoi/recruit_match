"""In-memory, deterministic pipeline execution over typed stage contracts.

This runner is deliberately adapter-agnostic. Stage handlers are injected by the
caller; this module does not perform network access or persistence. It stops
after the first unsuccessful or invalid stage and never claims out-of-scope
stages were executed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Any

from .pipeline import (
    RunContract,
    RunValidation,
    StageReceipt,
    StageStatus,
    validate_run,
)


@dataclass(frozen=True, slots=True)
class StageExecution:
    status: StageStatus
    output: Mapping[str, Any]
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineExecution:
    run_id: str
    receipts: tuple[StageReceipt, ...]
    validation: RunValidation
    context: Mapping[str, Any]


StageHandler = Callable[[Mapping[str, Any]], StageExecution]


def execute_pipeline(
    contract: RunContract,
    handlers: Mapping[str, StageHandler],
    initial_context: Mapping[str, Any] | None = None,
) -> PipelineExecution:
    """Execute in-scope stages in declared order, stopping on any non-success.

    NOT_APPLICABLE is accepted only when the stage contract explicitly permits
    it. Context is returned in memory only; callers are responsible for
    redaction and private persistence if they choose to persist anything.
    """
    context: dict[str, Any] = dict(initial_context or {})
    receipts: list[StageReceipt] = []
    by_id = {spec.stage_id: spec for spec in contract.stages}

    for stage_id in contract.in_scope_stage_ids:
        spec = by_id[stage_id]
        missing_predecessors = [
            predecessor
            for predecessor in spec.predecessors
            if predecessor not in {receipt.stage_id for receipt in receipts}
        ]
        if missing_predecessors:
            receipts.append(
                StageReceipt(
                    run_id=contract.run_id,
                    stage_id=stage_id,
                    status=StageStatus.BLOCKED,
                    attempt=1,
                    predecessor_stage_ids=spec.predecessors,
                    reason="PREDECESSOR_RECEIPT_MISSING",
                )
            )
            break

        if any(
            receipt.stage_id in spec.predecessors
            and not (
                receipt.status is StageStatus.SUCCESS
                or (
                    receipt.status is StageStatus.NOT_APPLICABLE
                    and by_id[receipt.stage_id].allow_not_applicable
                )
            )
            for receipt in receipts
        ):
            receipts.append(
                StageReceipt(
                    run_id=contract.run_id,
                    stage_id=stage_id,
                    status=StageStatus.BLOCKED,
                    attempt=1,
                    predecessor_stage_ids=spec.predecessors,
                    reason="PREDECESSOR_NOT_ACCEPTABLE",
                )
            )
            break

        handler = handlers.get(stage_id)
        if handler is None:
            receipts.append(
                StageReceipt(
                    run_id=contract.run_id,
                    stage_id=stage_id,
                    status=StageStatus.BLOCKED,
                    attempt=1,
                    predecessor_stage_ids=spec.predecessors,
                    reason="HANDLER_NOT_CONFIGURED",
                )
            )
            break

        try:
            result = handler(dict(context))
            if not isinstance(result, StageExecution):
                raise TypeError("HANDLER_RESULT_MUST_BE_STAGE_EXECUTION")
            if not isinstance(result.status, StageStatus):
                raise TypeError("HANDLER_STATUS_MUST_BE_STAGE_STATUS")
            if not isinstance(result.output, Mapping):
                raise TypeError("HANDLER_OUTPUT_MUST_BE_MAPPING")
        except Exception:
            # Do not propagate exception messages, which can contain secrets or
            # source/candidate content. Detailed diagnostics belong in a
            # separately controlled, redacted observability adapter.
            receipts.append(
                StageReceipt(
                    run_id=contract.run_id,
                    stage_id=stage_id,
                    status=StageStatus.FAILED,
                    attempt=1,
                    predecessor_stage_ids=spec.predecessors,
                    reason="STAGE_HANDLER_EXCEPTION",
                )
            )
            break

        try:
            receipt = StageReceipt(
                run_id=contract.run_id,
                stage_id=stage_id,
                status=result.status,
                attempt=1,
                predecessor_stage_ids=spec.predecessors,
                output_refs=result.output_refs,
                evidence_refs=result.evidence_refs,
                reason=result.reason,
            )
        except (TypeError, ValueError):
            receipts.append(
                StageReceipt(
                    run_id=contract.run_id,
                    stage_id=stage_id,
                    status=StageStatus.FAILED,
                    attempt=1,
                    predecessor_stage_ids=spec.predecessors,
                    reason="HANDLER_RETURN_INVALID",
                )
            )
            break
        receipts.append(receipt)

        if result.status is StageStatus.SUCCESS:
            context.update(result.output)
            continue
        if result.status is StageStatus.NOT_APPLICABLE and spec.allow_not_applicable:
            context.update(result.output)
            continue
        break

    validation = validate_run(contract, receipts)
    return PipelineExecution(
        run_id=contract.run_id,
        receipts=tuple(receipts),
        validation=validation,
        context=context,
    )
