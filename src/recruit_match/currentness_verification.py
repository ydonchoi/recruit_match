"""Currentness verification stage; currentness is not eligibility.

The injected verifier must inspect an identity-resolved, official source and
return a typed CurrentnessState with timestamped evidence. UNKNOWN blocks the
stage. This module performs no network I/O and does not infer currentness from
a search result's age or last commit.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .domain import CurrentnessState
from .pipeline import StageStatus
from .runner import StageExecution
from .source_verification import SourceAuthorityStatus, SourceVerificationReceipt


@dataclass(frozen=True, slots=True)
class CurrentnessDecision:
    source_result_ref: str
    opportunity_id: str
    state: CurrentnessState
    verifier_id: str
    observed_at: str
    basis: str | None = None
    evidence_refs: tuple[str, ...] = ()
    deadline_at: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("CURRENTNESS_SOURCE_REF_REQUIRED", self.source_result_ref),
            ("CURRENTNESS_OPPORTUNITY_ID_REQUIRED", self.opportunity_id),
            ("CURRENTNESS_VERIFIER_ID_REQUIRED", self.verifier_id),
            ("CURRENTNESS_OBSERVED_AT_REQUIRED", self.observed_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        if not isinstance(self.state, CurrentnessState):
            raise ValueError("CURRENTNESS_STATE_INVALID")
        try:
            observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("CURRENTNESS_OBSERVED_AT_INVALID") from exc
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("CURRENTNESS_OBSERVED_AT_MUST_BE_AWARE")
        if self.deadline_at is not None:
            if not isinstance(self.deadline_at, str) or not self.deadline_at.strip():
                raise ValueError("CURRENTNESS_DEADLINE_INVALID")
            try:
                deadline = datetime.fromisoformat(self.deadline_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("CURRENTNESS_DEADLINE_INVALID") from exc
            if deadline.tzinfo is None or deadline.utcoffset() is None:
                raise ValueError("CURRENTNESS_DEADLINE_MUST_BE_AWARE")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise ValueError("CURRENTNESS_EVIDENCE_REFS_INVALID")
        if self.state is not CurrentnessState.UNKNOWN:
            if not isinstance(self.basis, str) or not self.basis.strip():
                raise ValueError("CLASSIFIED_CURRENTNESS_REQUIRES_BASIS")
            if not self.evidence_refs:
                raise ValueError("CLASSIFIED_CURRENTNESS_REQUIRES_EVIDENCE")


@dataclass(frozen=True, slots=True)
class CurrentnessReceipt:
    source_result_ref: str
    opportunity_id: str
    state: CurrentnessState
    verifier_id: str
    observed_at: str
    basis: str | None
    evidence_refs: tuple[str, ...]
    deadline_at: str | None = None
    error_code: str | None = None


CurrentnessVerifier = Callable[[Any], CurrentnessDecision]


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def build_currentness_verification_handler(
    verifier: CurrentnessVerifier,
    *,
    verifier_id: str,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    if not callable(verifier):
        raise ValueError("CURRENTNESS_VERIFIER_REQUIRED")
    if not isinstance(verifier_id, str) or not verifier_id.strip():
        raise ValueError("CURRENTNESS_VERIFIER_ID_REQUIRED")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        official = context.get("official_source_results")
        if not isinstance(official, Sequence) or isinstance(official, (str, bytes, bytearray, Mapping)) or not official:
            return StageExecution(StageStatus.BLOCKED, {}, reason="OFFICIAL_SOURCE_RESULTS_MISSING")

        source_receipts = context.get("source_verification_receipts")
        if not isinstance(source_receipts, Sequence) or isinstance(source_receipts, (str, bytes, bytearray, Mapping)):
            return StageExecution(StageStatus.BLOCKED, {}, reason="SOURCE_VERIFICATION_RECEIPTS_MISSING")
        verified_official_receipts = {}
        for source_receipt in source_receipts:
            if not isinstance(source_receipt, SourceVerificationReceipt):
                continue
            try:
                source_receipt.__post_init__()
            except Exception:
                continue
            if source_receipt.status is SourceAuthorityStatus.VERIFIED_OFFICIAL:
                verified_official_receipts[source_receipt.source_result_ref] = source_receipt
        preflight: list[Any] = []
        seen_refs: set[str] = set()
        seen_opportunities: set[str] = set()
        for source in official:
            result_ref = _field(source, "source_result_ref")
            opportunity_id = _field(source, "opportunity_id")
            if not isinstance(result_ref, str) or not result_ref.strip():
                return StageExecution(StageStatus.BLOCKED, {}, reason="OFFICIAL_SOURCE_REF_MISSING")
            if result_ref in seen_refs:
                return StageExecution(StageStatus.BLOCKED, {}, reason="DUPLICATE_OFFICIAL_SOURCE_REF")
            seen_refs.add(result_ref)
            authority_receipt = verified_official_receipts.get(result_ref)
            if authority_receipt is None or authority_receipt.source_url != _field(source, "source_url"):
                return StageExecution(StageStatus.BLOCKED, {}, reason="OFFICIAL_SOURCE_AUTHORITY_NOT_CONFIRMED")
            if not isinstance(opportunity_id, str) or not opportunity_id.strip():
                return StageExecution(StageStatus.BLOCKED, {}, reason="OFFICIAL_OPPORTUNITY_ID_MISSING")
            if opportunity_id in seen_opportunities:
                return StageExecution(StageStatus.BLOCKED, {}, reason="DUPLICATE_OFFICIAL_OPPORTUNITY_ID")
            seen_opportunities.add(opportunity_id)
            preflight.append(source)

        receipts: list[CurrentnessReceipt] = []
        unknown_count = 0
        for source in preflight:
            result_ref = _field(source, "source_result_ref")
            opportunity_id = _field(source, "opportunity_id")
            try:
                decision = verifier(source)
                if not isinstance(decision, CurrentnessDecision):
                    raise ValueError("CURRENTNESS_VERIFIER_RESULT_INVALID")
                decision.__post_init__()
                if decision.source_result_ref != result_ref or decision.opportunity_id != opportunity_id:
                    raise ValueError("CURRENTNESS_IDENTITY_MISMATCH")
            except Exception:
                unknown_count += 1
                receipts.append(CurrentnessReceipt(
                    source_result_ref=result_ref,
                    opportunity_id=opportunity_id,
                    state=CurrentnessState.UNKNOWN,
                    verifier_id=verifier_id,
                    observed_at="",
                    basis=None,
                    evidence_refs=(),
                    error_code="CURRENTNESS_VERIFICATION_FAILED",
                ))
                continue
            receipts.append(CurrentnessReceipt(
                source_result_ref=result_ref,
                opportunity_id=opportunity_id,
                state=decision.state,
                verifier_id=decision.verifier_id,
                observed_at=decision.observed_at,
                basis=decision.basis,
                evidence_refs=decision.evidence_refs,
                deadline_at=decision.deadline_at,
            ))
            if decision.state is CurrentnessState.UNKNOWN:
                unknown_count += 1

        evidence_refs = tuple(
            f"currentness-verification:{r.source_result_ref}:{r.verifier_id}"
            for r in receipts
            if r.state is not CurrentnessState.UNKNOWN and r.evidence_refs
        )
        output = {
            "currentness_receipts": tuple(receipts),
            "currentness_by_opportunity_id": {
                receipt.opportunity_id: receipt.state for receipt in receipts
            },
            "currentness_verification_state": "INCOMPLETE" if unknown_count else "COMPLETE",
            "currentness_unknown_count": unknown_count,
            "currentness_classified_count": len(receipts) - unknown_count,
        }
        if unknown_count:
            return StageExecution(
                StageStatus.BLOCKED, output, evidence_refs=evidence_refs,
                reason="CURRENTNESS_UNKNOWN",
            )
        if not evidence_refs:
            return StageExecution(
                StageStatus.BLOCKED, output,
                reason="CURRENTNESS_EVIDENCE_MISSING",
            )
        return StageExecution(
            StageStatus.SUCCESS, output,
            output_refs=tuple(receipt.source_result_ref for receipt in receipts),
            evidence_refs=evidence_refs,
        )

    return handler
