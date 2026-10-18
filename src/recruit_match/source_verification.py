"""Source-authority verification stage with an explicitly injected verifier.

Discovery and source authority are separate. A URL returned by search is not
considered official merely because it is syntactically valid or reachable.
This module records the verifier's decision and blocks the pipeline when that
decision is unknown or malformed. It does not itself fetch the web or infer
official status from hostnames.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from .pipeline import StageStatus
from .runner import StageExecution


class SourceAuthorityStatus(StrEnum):
    VERIFIED_OFFICIAL = "VERIFIED_OFFICIAL"
    VERIFIED_NON_OFFICIAL = "VERIFIED_NON_OFFICIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SourceAuthorityDecision:
    status: SourceAuthorityStatus
    verifier_id: str
    observed_at: str
    authority_basis: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, SourceAuthorityStatus):
            raise ValueError("SOURCE_AUTHORITY_STATUS_INVALID")
        if not isinstance(self.verifier_id, str) or not self.verifier_id.strip():
            raise ValueError("SOURCE_VERIFIER_ID_REQUIRED")
        if not isinstance(self.observed_at, str) or not self.observed_at.strip():
            raise ValueError("SOURCE_VERIFICATION_TIMESTAMP_REQUIRED")
        try:
            parsed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("SOURCE_VERIFICATION_TIMESTAMP_INVALID") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("SOURCE_VERIFICATION_TIMESTAMP_MUST_BE_AWARE")
        if self.status in (SourceAuthorityStatus.VERIFIED_OFFICIAL, SourceAuthorityStatus.VERIFIED_NON_OFFICIAL):
            if not isinstance(self.authority_basis, str) or not self.authority_basis.strip():
                raise ValueError("VERIFIED_SOURCE_REQUIRES_AUTHORITY_BASIS")
            if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs or any(
                not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
            ):
                raise ValueError("VERIFIED_SOURCE_REQUIRES_EVIDENCE_REFS")
        elif self.authority_basis is not None and not isinstance(self.authority_basis, str):
            raise ValueError("SOURCE_AUTHORITY_BASIS_INVALID")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise ValueError("SOURCE_AUTHORITY_EVIDENCE_REFS_INVALID")


@dataclass(frozen=True, slots=True)
class SourceVerificationReceipt:
    source_result_ref: str
    source_url: str
    status: SourceAuthorityStatus
    verifier_id: str
    observed_at: str
    authority_basis: str | None
    evidence_refs: tuple[str, ...]
    error_code: str | None = None


SourceVerifier = Callable[[Any], SourceAuthorityDecision]


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def build_source_verification_handler(
    verifier: SourceVerifier,
    *,
    default_verifier_id: str,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    """Build a fail-closed verifier stage over discovered search results."""
    if not callable(verifier):
        raise ValueError("SOURCE_VERIFIER_REQUIRED")
    if not isinstance(default_verifier_id, str) or not default_verifier_id.strip():
        raise ValueError("DEFAULT_SOURCE_VERIFIER_ID_REQUIRED")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        discovered = context.get("resolved_opportunity_sources")
        if not isinstance(discovered, Sequence) or isinstance(discovered, (str, bytes, bytearray, Mapping)) or not discovered:
            return StageExecution(StageStatus.BLOCKED, {}, reason="RESOLVED_OPPORTUNITY_SOURCES_MISSING")

        # Validate the entire input batch before invoking any external verifier.
        preflight: list[tuple[Any, str, str]] = []
        seen_refs: set[str] = set()
        for item in discovered:
            result_ref = _field(item, "source_result_ref") or _field(item, "result_ref")
            source_url = _field(item, "source_url")
            if not isinstance(result_ref, str) or not result_ref.strip():
                return StageExecution(StageStatus.BLOCKED, {}, reason="DISCOVERED_RESULT_REF_MISSING")
            if result_ref in seen_refs:
                return StageExecution(StageStatus.BLOCKED, {}, reason="DUPLICATE_DISCOVERED_RESULT_REF")
            seen_refs.add(result_ref)
            if not isinstance(source_url, str) or not source_url.strip():
                return StageExecution(StageStatus.BLOCKED, {}, reason="DISCOVERED_SOURCE_URL_MISSING")
            parsed = urlsplit(source_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                return StageExecution(StageStatus.BLOCKED, {}, reason="DISCOVERED_SOURCE_URL_INVALID")
            preflight.append((item, result_ref, source_url))

        receipts: list[SourceVerificationReceipt] = []
        official: list[Any] = []
        unknown_count = 0
        for item, result_ref, source_url in preflight:
            try:
                decision = verifier(item)
                if not isinstance(decision, SourceAuthorityDecision):
                    raise ValueError("SOURCE_VERIFIER_RESULT_INVALID")
                # Revalidate frozen dataclass instances at this trust boundary.
                decision.__post_init__()
            except Exception:
                unknown_count += 1
                receipts.append(SourceVerificationReceipt(
                    source_result_ref=result_ref,
                    source_url=source_url,
                    status=SourceAuthorityStatus.UNKNOWN,
                    verifier_id=default_verifier_id,
                    observed_at="",
                    authority_basis=None,
                    evidence_refs=(),
                    error_code="SOURCE_AUTHORITY_VERIFICATION_FAILED",
                ))
                continue

            receipts.append(SourceVerificationReceipt(
                source_result_ref=result_ref,
                source_url=source_url,
                status=decision.status,
                verifier_id=decision.verifier_id,
                observed_at=decision.observed_at,
                authority_basis=decision.authority_basis,
                evidence_refs=decision.evidence_refs,
            ))
            if decision.status is SourceAuthorityStatus.VERIFIED_OFFICIAL:
                official.append(item)
            elif decision.status is SourceAuthorityStatus.UNKNOWN:
                unknown_count += 1

        evidence_refs = tuple(
            f"source-verification:{receipt.source_result_ref}:{receipt.verifier_id}"
            for receipt in receipts
            if receipt.status is not SourceAuthorityStatus.UNKNOWN and receipt.evidence_refs
        )
        output = {
            "source_verification_receipts": tuple(receipts),
            "official_source_results": tuple(official),
            "source_verification_state": "INCOMPLETE" if unknown_count else (
                "COMPLETE_WITH_OFFICIAL_SOURCES" if official else "COMPLETE_NO_OFFICIAL_SOURCE"
            ),
            "source_verification_unknown_count": unknown_count,
            "official_source_count": len(official),
        }
        if unknown_count:
            return StageExecution(
                StageStatus.BLOCKED, output, evidence_refs=evidence_refs,
                reason="SOURCE_AUTHORITY_UNKNOWN",
            )
        if not evidence_refs:
            return StageExecution(
                StageStatus.BLOCKED, output,
                reason="SOURCE_VERIFICATION_EVIDENCE_MISSING",
            )
        return StageExecution(
            StageStatus.SUCCESS, output,
            output_refs=tuple(receipt.source_result_ref for receipt in receipts),
            evidence_refs=evidence_refs,
        )

    return handler
