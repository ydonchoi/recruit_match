"""In-memory, deterministic pipeline execution over typed stage contracts.

This runner is deliberately adapter-agnostic. Stage handlers are injected by the
caller; this module does not perform network access or persistence. It stops
after the first unsuccessful or invalid stage and never claims out-of-scope
stages were executed.
"""
from __future__ import annotations

from copy import deepcopy
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
    if not isinstance(contract, RunContract):
        raise ValueError("INVALID_RUN_CONTRACT")
    if not isinstance(handlers, Mapping):
        raise ValueError("HANDLERS_MUST_BE_MAPPING")
    if any(
        not isinstance(name, str) or not name.strip() or not callable(handler)
        for name, handler in handlers.items()
    ):
        raise ValueError("INVALID_HANDLER_REGISTRY")
    if initial_context is not None and not isinstance(initial_context, Mapping):
        raise ValueError("INITIAL_CONTEXT_MUST_BE_MAPPING")
    if initial_context is not None and any(
        not isinstance(key, str) or not key.strip() for key in initial_context
    ):
        raise ValueError("INITIAL_CONTEXT_KEYS_MUST_BE_STRINGS")
    try:
        context: dict[str, Any] = deepcopy(dict(initial_context)) if initial_context is not None else {}
    except Exception as exc:
        raise ValueError("INITIAL_CONTEXT_NOT_COPYABLE") from exc
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
            # Isolate nested mutable values so a handler cannot mutate the
            # runner's context by modifying a shallow-copied list/dict in place.
            result = handler(deepcopy(context))
            if not isinstance(result, StageExecution):
                raise TypeError("HANDLER_RESULT_MUST_BE_STAGE_EXECUTION")
            if not isinstance(result.status, StageStatus):
                raise TypeError("HANDLER_STATUS_MUST_BE_STAGE_STATUS")
            if not isinstance(result.output, Mapping):
                raise TypeError("HANDLER_OUTPUT_MUST_BE_MAPPING")
            if any(not isinstance(key, str) or not key.strip() for key in result.output):
                raise TypeError("HANDLER_OUTPUT_KEYS_MUST_BE_STRINGS")
            for name, refs in (
                ("OUTPUT_REFS", result.output_refs),
                ("EVIDENCE_REFS", result.evidence_refs),
            ):
                if not isinstance(refs, tuple) or any(
                    not isinstance(ref, str) or not ref.strip() for ref in refs
                ):
                    raise TypeError(f"HANDLER_{name}_INVALID")
            if result.reason is not None and (
                not isinstance(result.reason, str) or not result.reason.strip()
            ):
                raise TypeError("HANDLER_REASON_INVALID")
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

        if spec.evidence_required and not result.evidence_refs:
            receipts.append(
                StageReceipt(
                    run_id=contract.run_id,
                    stage_id=stage_id,
                    status=StageStatus.FAILED,
                    attempt=1,
                    predecessor_stage_ids=spec.predecessors,
                    reason="STAGE_EVIDENCE_MISSING",
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

        # Preserve a well-formed unsuccessful stage's diagnostic output in the
        # returned in-memory context. The runner still stops immediately, so no
        # downstream handler can consume partial results as if the stage passed.
        # This is needed to inspect search-budget receipts after a partial/failed
        # discovery stage; it does not mark the run valid.
        context.update(deepcopy(dict(result.output)))
        if result.status is StageStatus.SUCCESS:
            continue
        if result.status is StageStatus.NOT_APPLICABLE and spec.allow_not_applicable:
            continue
        break

    validation = validate_run(contract, receipts)
    return PipelineExecution(
        run_id=contract.run_id,
        receipts=tuple(receipts),
        validation=validation,
        context=context,
    )
