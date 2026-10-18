"""Identity-resolution stage with an explicit detail/identity resolver.

Search-result IDs and URLs are not treated as stable recruitment-opportunity
identities. The injected resolver must return traceable identity evidence,
including a recruitment-cycle identity and posting ID, or the stage blocks.
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


class IdentityResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OpportunityIdentityDecision:
    source_result_ref: str
    status: IdentityResolutionStatus
    resolver_id: str
    observed_at: str
    opportunity_id: str | None = None
    organization: str | None = None
    position: str | None = None
    recruitment_cycle: str | None = None
    posting_id: str | None = None
    identity_basis: str | None = None
    evidence_refs: tuple[str, ...] = ()
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_result_ref, str) or not self.source_result_ref.strip():
            raise ValueError("IDENTITY_SOURCE_RESULT_REF_REQUIRED")
        if not isinstance(self.status, IdentityResolutionStatus):
            raise ValueError("IDENTITY_STATUS_INVALID")
        if not isinstance(self.resolver_id, str) or not self.resolver_id.strip():
            raise ValueError("IDENTITY_RESOLVER_ID_REQUIRED")
        if not isinstance(self.observed_at, str) or not self.observed_at.strip():
            raise ValueError("IDENTITY_OBSERVED_AT_REQUIRED")
        try:
            parsed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("IDENTITY_OBSERVED_AT_INVALID") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("IDENTITY_OBSERVED_AT_MUST_BE_AWARE")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise ValueError("IDENTITY_EVIDENCE_REFS_INVALID")
        if self.status is IdentityResolutionStatus.RESOLVED:
            fields = (
                self.opportunity_id, self.organization, self.position,
                self.recruitment_cycle, self.posting_id, self.identity_basis,
            )
            if any(not isinstance(value, str) or not value.strip() for value in fields):
                raise ValueError("RESOLVED_IDENTITY_FIELDS_REQUIRED")
            if not self.evidence_refs:
                raise ValueError("RESOLVED_IDENTITY_REQUIRES_EVIDENCE")


@dataclass(frozen=True, slots=True)
class ResolvedOpportunitySource:
    source_result_ref: str
    provider_id: str
    provider_result_id: str
    source_url: str
    title: str
    observed_at: str
    query_sha256: str
    opportunity_id: str
    organization: str
    position: str
    recruitment_cycle: str
    posting_id: str
    identity_basis: str
    identity_evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IdentityResolutionReceipt:
    source_result_ref: str
    resolver_id: str
    status: IdentityResolutionStatus
    opportunity_id: str | None
    observed_at: str
    evidence_refs: tuple[str, ...]
    duplicate_of: str | None = None
    error_code: str | None = None


IdentityResolver = Callable[[Any], OpportunityIdentityDecision]


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def build_identity_resolution_handler(
    resolver: IdentityResolver,
    *,
    resolver_id: str,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    if not callable(resolver):
        raise ValueError("IDENTITY_RESOLVER_REQUIRED")
    if not isinstance(resolver_id, str) or not resolver_id.strip():
        raise ValueError("IDENTITY_RESOLVER_ID_REQUIRED")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        discovered = context.get("discovered_search_results")
        if not isinstance(discovered, Sequence) or isinstance(discovered, (str, bytes, bytearray, Mapping)) or not discovered:
            return StageExecution(StageStatus.BLOCKED, {}, reason="DISCOVERED_SEARCH_RESULTS_MISSING")

        preflight: list[tuple[Any, str, str]] = []
        seen_refs: set[str] = set()
        for item in discovered:
            result_ref = _field(item, "result_ref")
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
            for field in ("provider_id", "provider_result_id", "title", "observed_at", "query_sha256"):
                value = _field(item, field)
                if not isinstance(value, str) or not value.strip():
                    return StageExecution(StageStatus.BLOCKED, {}, reason=f"DISCOVERED_{field.upper()}_MISSING")
            preflight.append((item, result_ref, source_url))

        resolved: list[ResolvedOpportunitySource] = []
        receipts: list[IdentityResolutionReceipt] = []
        unknown_count = 0
        conflict = False
        seen_identity: dict[str, ResolvedOpportunitySource] = {}

        for item, result_ref, source_url in preflight:
            try:
                decision = resolver(item)
                if not isinstance(decision, OpportunityIdentityDecision):
                    raise ValueError("IDENTITY_RESOLVER_RESULT_INVALID")
                decision.__post_init__()
                if decision.source_result_ref != result_ref:
                    raise ValueError("IDENTITY_RESULT_REFERENCE_MISMATCH")
            except Exception:
                unknown_count += 1
                receipts.append(IdentityResolutionReceipt(
                    source_result_ref=result_ref, resolver_id=resolver_id,
                    status=IdentityResolutionStatus.UNKNOWN, opportunity_id=None,
                    observed_at="", evidence_refs=(), error_code="IDENTITY_RESOLUTION_FAILED",
                ))
                continue

            if decision.status is not IdentityResolutionStatus.RESOLVED:
                unknown_count += 1
                receipts.append(IdentityResolutionReceipt(
                    source_result_ref=result_ref, resolver_id=decision.resolver_id,
                    status=decision.status, opportunity_id=decision.opportunity_id,
                    observed_at=decision.observed_at, evidence_refs=decision.evidence_refs,
                    error_code=decision.reason_code or "IDENTITY_NOT_RESOLVED",
                ))
                continue

            source = ResolvedOpportunitySource(
                source_result_ref=result_ref,
                provider_id=_field(item, "provider_id"),
                provider_result_id=_field(item, "provider_result_id"),
                source_url=source_url,
                title=_field(item, "title"),
                observed_at=_field(item, "observed_at"),
                query_sha256=_field(item, "query_sha256"),
                opportunity_id=decision.opportunity_id,
                organization=decision.organization,
                position=decision.position,
                recruitment_cycle=decision.recruitment_cycle,
                posting_id=decision.posting_id,
                identity_basis=decision.identity_basis,
                identity_evidence_refs=decision.evidence_refs,
            )
            existing = seen_identity.get(source.opportunity_id)
            duplicate_of = None
            if existing is not None:
                same_identity = (
                    existing.organization == source.organization
                    and existing.position == source.position
                    and existing.recruitment_cycle == source.recruitment_cycle
                    and existing.posting_id == source.posting_id
                    and existing.source_url == source.source_url
                )
                if not same_identity:
                    conflict = True
                    receipts.append(IdentityResolutionReceipt(
                        source_result_ref=result_ref, resolver_id=decision.resolver_id,
                        status=IdentityResolutionStatus.AMBIGUOUS,
                        opportunity_id=source.opportunity_id, observed_at=decision.observed_at,
                        evidence_refs=decision.evidence_refs, error_code="OPPORTUNITY_IDENTITY_CONFLICT",
                    ))
                    continue
                duplicate_of = existing.source_result_ref
            else:
                seen_identity[source.opportunity_id] = source
                resolved.append(source)

            receipts.append(IdentityResolutionReceipt(
                source_result_ref=result_ref, resolver_id=decision.resolver_id,
                status=IdentityResolutionStatus.RESOLVED,
                opportunity_id=source.opportunity_id, observed_at=decision.observed_at,
                evidence_refs=decision.evidence_refs, duplicate_of=duplicate_of,
            ))

        evidence_refs = tuple(
            f"identity-resolution:{r.source_result_ref}:{r.resolver_id}"
            for r in receipts
            if r.status is IdentityResolutionStatus.RESOLVED and r.evidence_refs
        )
        output = {
            "identity_resolution_receipts": tuple(receipts),
            "resolved_opportunity_sources": tuple(resolved),
            "identity_resolution_state": "INCOMPLETE" if unknown_count or conflict else "COMPLETE",
            "identity_resolution_unknown_count": unknown_count,
            "identity_conflict_detected": conflict,
            "resolved_opportunity_count": len(resolved),
            "duplicate_source_count": sum(r.duplicate_of is not None for r in receipts),
        }
        if unknown_count or conflict:
            return StageExecution(
                StageStatus.BLOCKED, output, evidence_refs=evidence_refs,
                reason="IDENTITY_RESOLUTION_INCOMPLETE",
            )
        if not resolved or not evidence_refs:
            return StageExecution(
                StageStatus.BLOCKED, output,
                reason="IDENTITY_RESOLUTION_EVIDENCE_MISSING",
            )
        return StageExecution(
            StageStatus.SUCCESS, output,
            output_refs=tuple(source.source_result_ref for source in resolved),
            evidence_refs=evidence_refs,
        )

    return handler
