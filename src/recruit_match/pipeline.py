"""Typed stage receipts and fail-closed validation for bounded analysis runs.

This module contains domain-level contracts only. It performs no I/O and has
no persistence, network, candidate-data, or application-submission authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping


class StageStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class StageSpec:
    stage_id: str
    required: bool = True
    allow_not_applicable: bool = False
    predecessors: tuple[str, ...] = ()
    evidence_required: bool = False


@dataclass(frozen=True, slots=True)
class StageReceipt:
    run_id: str
    stage_id: str
    status: StageStatus
    attempt: int
    predecessor_stage_ids: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("RUN_ID_REQUIRED")
        if not self.stage_id.strip():
            raise ValueError("STAGE_ID_REQUIRED")
        if not isinstance(self.status, StageStatus):
            raise ValueError("INVALID_STAGE_STATUS")
        if self.attempt < 1:
            raise ValueError("ATTEMPT_MUST_BE_POSITIVE")
        if self.status in (StageStatus.FAILED, StageStatus.BLOCKED) and not (
            self.reason and self.reason.strip()
        ):
            raise ValueError("NON_SUCCESS_REQUIRES_REASON")
        if self.status is StageStatus.NOT_APPLICABLE and not (
            self.reason and self.reason.strip()
        ):
            raise ValueError("NOT_APPLICABLE_REQUIRES_REASON")
        if self.status is StageStatus.NOT_APPLICABLE and not self.evidence_refs:
            raise ValueError("NOT_APPLICABLE_REQUIRES_EVIDENCE")


@dataclass(frozen=True, slots=True)
class RunContract:
    """The explicit stage scope for one full or intentionally bounded run."""

    run_id: str
    stages: tuple[StageSpec, ...]
    bounded_through: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("RUN_ID_REQUIRED")
        ids = [stage.stage_id for stage in self.stages]
        if any(not stage_id.strip() for stage_id in ids):
            raise ValueError("STAGE_ID_REQUIRED")
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_STAGE_SPEC")
        for stage in self.stages:
            if len(stage.predecessors) != len(set(stage.predecessors)):
                raise ValueError(f"DUPLICATE_PREDECESSOR:{stage.stage_id}")
        if self.bounded_through is not None and self.bounded_through not in ids:
            raise ValueError("BOUNDARY_NOT_IN_RUN_SCOPE")
        seen: set[str] = set()
        for stage in self.stages:
            missing = set(stage.predecessors) - set(ids)
            if missing:
                raise ValueError(f"UNKNOWN_PREDECESSOR:{stage.stage_id}:{','.join(sorted(missing))}")
            if any(predecessor not in seen for predecessor in stage.predecessors):
                raise ValueError(f"PREDECESSOR_MUST_PRECEDE_STAGE:{stage.stage_id}")
            seen.add(stage.stage_id)

    @property
    def in_scope_stage_ids(self) -> tuple[str, ...]:
        ids = tuple(stage.stage_id for stage in self.stages)
        if self.bounded_through is None:
            return ids
        return ids[: ids.index(self.bounded_through) + 1]


@dataclass(frozen=True, slots=True)
class RunValidation:
    valid: bool
    issues: tuple[str, ...]
    completed_stage_ids: tuple[str, ...]


def validate_run(contract: RunContract, receipts: Iterable[StageReceipt]) -> RunValidation:
    """Validate one terminal receipt per in-scope stage and predecessor gating.

    The function validates a declared bounded run, not the entire system. A
    bounded run is valid only through its explicit endpoint; it makes no claim
    about out-of-scope stages.
    """
    issues: list[str] = []
    receipt_list = tuple(receipts)
    by_stage: dict[str, StageReceipt] = {}
    invalid_stage_ids: set[str] = set()

    for receipt in receipt_list:
        if receipt.run_id != contract.run_id:
            issues.append(f"RUN_ID_MISMATCH:{receipt.stage_id}")
            continue
        if receipt.stage_id in by_stage:
            issues.append(f"DUPLICATE_TERMINAL_RECEIPT:{receipt.stage_id}")
            invalid_stage_ids.add(receipt.stage_id)
            continue
        by_stage[receipt.stage_id] = receipt

    specs = {stage.stage_id: stage for stage in contract.stages}
    in_scope = contract.in_scope_stage_ids
    completed: list[str] = []
    accepted_predecessors: set[str] = set()

    for stage_id in in_scope:
        spec = specs[stage_id]
        receipt = by_stage.get(stage_id)
        if receipt is None:
            if spec.required:
                issues.append(f"MISSING_TERMINAL_RECEIPT:{stage_id}")
            continue

        issues_before_stage = len(issues)
        if receipt.status is StageStatus.FAILED or receipt.status is StageStatus.BLOCKED:
            issues.append(f"STAGE_TERMINAL_NOT_SUCCESS:{stage_id}:{receipt.status.value}")
        if receipt.status is StageStatus.NOT_APPLICABLE and not spec.allow_not_applicable:
            issues.append(f"NOT_APPLICABLE_NOT_ALLOWED:{stage_id}")
        if spec.evidence_required and not receipt.evidence_refs:
            issues.append(f"STAGE_EVIDENCE_MISSING:{stage_id}")

        declared_predecessors = set(spec.predecessors)
        observed_predecessors = set(receipt.predecessor_stage_ids)
        if declared_predecessors != observed_predecessors:
            issues.append(f"PREDECESSOR_SET_MISMATCH:{stage_id}")

        for predecessor_id in spec.predecessors:
            predecessor = by_stage.get(predecessor_id)
            if predecessor is None:
                issues.append(f"PREDECESSOR_RECEIPT_MISSING:{stage_id}:{predecessor_id}")
            elif predecessor.status is not StageStatus.SUCCESS and not (
                predecessor.status is StageStatus.NOT_APPLICABLE
                and specs[predecessor_id].allow_not_applicable
            ):
                issues.append(f"PREDECESSOR_NOT_TERMINALLY_ACCEPTABLE:{stage_id}:{predecessor_id}")
            elif predecessor_id not in accepted_predecessors:
                issues.append(f"PREDECESSOR_NOT_ACCEPTED:{stage_id}:{predecessor_id}")

        stage_accepted = (
            len(issues) == issues_before_stage
            and stage_id not in invalid_stage_ids
            and (
                receipt.status is StageStatus.SUCCESS
                or (
                    receipt.status is StageStatus.NOT_APPLICABLE
                    and spec.allow_not_applicable
                )
            )
        )
        if stage_accepted:
            accepted_predecessors.add(stage_id)
            if receipt.status is StageStatus.SUCCESS:
                completed.append(stage_id)

    out_of_scope = set(by_stage) - set(in_scope)
    if out_of_scope:
        issues.extend(f"OUT_OF_SCOPE_RECEIPT:{stage_id}" for stage_id in sorted(out_of_scope))

    return RunValidation(not issues, tuple(issues), tuple(completed))
