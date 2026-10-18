"""Policy-gated attachment acquisition and inspection stage adapters.

All discovery, policy evaluation, fetching, private content storage, and parsing
are injected. This module never puts raw document bytes into pipeline context.
The caller must provide a content sink before fetching can occur.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from .attachments import AttachmentLimits, AttachmentPolicy, AttachmentReceipt
from .pipeline import StageStatus
from .runner import StageExecution
from .source_verification import SourceAuthorityStatus, SourceVerificationReceipt


class AttachmentPolicyStatus(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AttachmentDiscoveryBatch:
    """Typed result from inspecting a verified official page for attachment links."""

    source_result_ref: str
    complete: bool
    candidates: tuple[AttachmentCandidate, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_result_ref, str) or not self.source_result_ref.strip():
            raise ValueError("ATTACHMENT_DISCOVERY_SOURCE_REF_REQUIRED")
        if not isinstance(self.complete, bool):
            raise ValueError("ATTACHMENT_DISCOVERY_COMPLETENESS_MUST_BE_BOOLEAN")
        if not isinstance(self.candidates, tuple) or any(
            not isinstance(item, AttachmentCandidate) for item in self.candidates
        ):
            raise ValueError("ATTACHMENT_DISCOVERY_CANDIDATES_INVALID")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise ValueError("ATTACHMENT_DISCOVERY_REQUIRES_EVIDENCE")


@dataclass(frozen=True, slots=True)
class AttachmentCandidate:
    attachment_ref: str
    source_result_ref: str
    attachment_url: str
    link_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("ATTACHMENT_REF_REQUIRED", self.attachment_ref),
            ("ATTACHMENT_SOURCE_REF_REQUIRED", self.source_result_ref),
            ("ATTACHMENT_URL_REQUIRED", self.attachment_url),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        parsed = urlsplit(self.attachment_url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("ATTACHMENT_URL_MUST_BE_HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("ATTACHMENT_URL_CREDENTIALS_FORBIDDEN")
        if parsed.port not in (None, 443):
            raise ValueError("ATTACHMENT_URL_NONSTANDARD_PORT_FORBIDDEN")
        if not isinstance(self.link_evidence_refs, tuple) or not self.link_evidence_refs or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.link_evidence_refs
        ):
            raise ValueError("ATTACHMENT_LINK_EVIDENCE_REQUIRED")


@dataclass(frozen=True, slots=True)
class AttachmentPolicyDecision:
    attachment_ref: str
    status: AttachmentPolicyStatus
    policy_id: str
    allowed_hosts: tuple[str, ...]
    max_bytes: int
    timeout_seconds: float
    robots_required: bool
    evidence_refs: tuple[str, ...]
    reason_code: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("ATTACHMENT_POLICY_REF_REQUIRED", self.attachment_ref),
            ("ATTACHMENT_POLICY_ID_REQUIRED", self.policy_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        if not isinstance(self.status, AttachmentPolicyStatus):
            raise ValueError("ATTACHMENT_POLICY_STATUS_INVALID")
        if not isinstance(self.allowed_hosts, tuple) or any(
            not isinstance(host, str) or not host.strip() for host in self.allowed_hosts
        ):
            raise ValueError("ATTACHMENT_ALLOWED_HOSTS_INVALID")
        if len({host.lower().rstrip(".") for host in self.allowed_hosts}) != len(self.allowed_hosts):
            raise ValueError("ATTACHMENT_ALLOWED_HOSTS_DUPLICATE")
        if not isinstance(self.max_bytes, int) or isinstance(self.max_bytes, bool) or self.max_bytes < 1:
            raise ValueError("ATTACHMENT_MAX_BYTES_MUST_BE_POSITIVE_INTEGER")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("ATTACHMENT_TIMEOUT_MUST_BE_FINITE_AND_POSITIVE")
        if not isinstance(self.robots_required, bool):
            raise ValueError("ATTACHMENT_ROBOTS_REQUIRED_MUST_BE_BOOLEAN")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise ValueError("ATTACHMENT_POLICY_EVIDENCE_REFS_INVALID")
        if self.status in (AttachmentPolicyStatus.ALLOW, AttachmentPolicyStatus.DENY) and not self.evidence_refs:
            raise ValueError("DECIDED_ATTACHMENT_POLICY_REQUIRES_EVIDENCE")
        if self.status is AttachmentPolicyStatus.ALLOW and not self.allowed_hosts:
            raise ValueError("ALLOWED_ATTACHMENT_POLICY_REQUIRES_HOST_ALLOWLIST")
        if self.status is AttachmentPolicyStatus.DENY and not (
            isinstance(self.reason_code, str) and self.reason_code.strip()
        ):
            raise ValueError("DENIED_ATTACHMENT_POLICY_REQUIRES_REASON")


@dataclass(frozen=True, slots=True)
class AttachmentPolicyReceipt:
    attachment_ref: str
    source_result_ref: str
    attachment_url: str
    status: AttachmentPolicyStatus
    policy_id: str
    allowed_hosts: tuple[str, ...]
    max_bytes: int
    timeout_seconds: float
    robots_required: bool
    evidence_refs: tuple[str, ...]
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovedAttachment:
    candidate: AttachmentCandidate
    policy: AttachmentPolicyDecision


@dataclass(frozen=True, slots=True)
class AttachmentFetchResult:
    attachment_ref: str
    source_result_ref: str
    source_url: str
    final_url: str | None
    content_ref: str | None
    fetched_at_epoch: float | None
    content_type: str | None
    byte_size: int
    sha256: str | None
    media_kind: str | None
    status: str
    policy_id: str
    evidence_refs: tuple[str, ...]
    error_code: str | None = None


class AttachmentInspectionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AttachmentEvidenceItem:
    evidence_id: str
    requirement_text: str
    requirement_kind: str
    source_location: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value in (
            ("ATTACHMENT_EVIDENCE_ID_REQUIRED", self.evidence_id),
            ("ATTACHMENT_REQUIREMENT_TEXT_REQUIRED", self.requirement_text),
            ("ATTACHMENT_REQUIREMENT_KIND_REQUIRED", self.requirement_kind),
            ("ATTACHMENT_SOURCE_LOCATION_REQUIRED", self.source_location),
            ("ATTACHMENT_EVIDENCE_REF_REQUIRED", self.evidence_ref),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        if self.requirement_kind not in {"MANDATORY", "PREFERRED", "COMPENSATION", "APPLICATION_DOCUMENT", "OTHER"}:
            raise ValueError("ATTACHMENT_REQUIREMENT_KIND_INVALID")


@dataclass(frozen=True, slots=True)
class AttachmentInspectionDecision:
    attachment_ref: str
    content_ref: str
    status: AttachmentInspectionStatus
    inspector_id: str
    observed_at: str
    evidence_refs: tuple[str, ...]
    extracted_items: tuple[AttachmentEvidenceItem, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("INSPECTION_ATTACHMENT_REF_REQUIRED", self.attachment_ref),
            ("INSPECTION_CONTENT_REF_REQUIRED", self.content_ref),
            ("INSPECTOR_ID_REQUIRED", self.inspector_id),
            ("INSPECTION_OBSERVED_AT_REQUIRED", self.observed_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(name)
        if not isinstance(self.status, AttachmentInspectionStatus):
            raise ValueError("ATTACHMENT_INSPECTION_STATUS_INVALID")
        try:
            observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("INSPECTION_TIMESTAMP_INVALID") from exc
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("INSPECTION_TIMESTAMP_MUST_BE_AWARE")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise ValueError("INSPECTION_EVIDENCE_REFS_INVALID")
        if not isinstance(self.extracted_items, tuple) or any(
            not isinstance(item, AttachmentEvidenceItem) for item in self.extracted_items
        ):
            raise ValueError("INSPECTION_EXTRACTED_ITEMS_INVALID")
        if not isinstance(self.limitations, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.limitations
        ):
            raise ValueError("INSPECTION_LIMITATIONS_INVALID")
        if self.status is AttachmentInspectionStatus.COMPLETE and not self.evidence_refs:
            raise ValueError("COMPLETE_INSPECTION_REQUIRES_EVIDENCE")


AttachmentDiscoverer = Callable[[Any], AttachmentDiscoveryBatch]
AttachmentPolicyEvaluator = Callable[[AttachmentCandidate, Any], AttachmentPolicyDecision]
AttachmentFetcherFactory = Callable[[AttachmentPolicy, AttachmentLimits], Any]
PrivateContentSink = Callable[[AttachmentCandidate, AttachmentReceipt], str]
AttachmentInspector = Callable[[str, AttachmentFetchResult], AttachmentInspectionDecision]


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _official_sources(context: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    sources = context.get("official_source_results")
    receipts = context.get("source_verification_receipts")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes, bytearray, Mapping)) or not sources:
        return {}, "OFFICIAL_SOURCE_RESULTS_MISSING"
    if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes, bytearray, Mapping)):
        return {}, "SOURCE_VERIFICATION_RECEIPTS_MISSING"
    verified: dict[str, Any] = {}
    for receipt in receipts:
        if not isinstance(receipt, SourceVerificationReceipt):
            continue
        try:
            receipt.__post_init__()
        except Exception:
            continue
        if receipt.status is SourceAuthorityStatus.VERIFIED_OFFICIAL:
            verified[receipt.source_result_ref] = receipt
    source_map: dict[str, Any] = {}
    for source in sources:
        ref = _field(source, "source_result_ref")
        url = _field(source, "source_url")
        if not isinstance(ref, str) or not ref.strip() or not isinstance(url, str) or not url.strip():
            return {}, "OFFICIAL_SOURCE_IDENTITY_INVALID"
        receipt = verified.get(ref)
        if receipt is None or receipt.source_url != url:
            return {}, "OFFICIAL_SOURCE_AUTHORITY_NOT_CONFIRMED"
        if ref in source_map:
            return {}, "DUPLICATE_OFFICIAL_SOURCE_REF"
        source_map[ref] = source
    return source_map, None


def build_attachment_policy_handler(
    discover_attachments: AttachmentDiscoverer,
    evaluate_policy: AttachmentPolicyEvaluator,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    if not callable(discover_attachments):
        raise ValueError("ATTACHMENT_DISCOVERER_REQUIRED")
    if not callable(evaluate_policy):
        raise ValueError("ATTACHMENT_POLICY_EVALUATOR_REQUIRED")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        source_map, error = _official_sources(context)
        if error:
            return StageExecution(StageStatus.BLOCKED, {}, reason=error)

        candidates: list[AttachmentCandidate] = []
        discovery_refs: list[str] = []
        for source_ref, source in source_map.items():
            try:
                batch = discover_attachments(source)
                if not isinstance(batch, AttachmentDiscoveryBatch):
                    raise ValueError("ATTACHMENT_DISCOVERY_RESULT_INVALID")
                batch.__post_init__()
                if batch.source_result_ref != source_ref:
                    raise ValueError("ATTACHMENT_DISCOVERY_SOURCE_MISMATCH")
            except Exception:
                return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_DISCOVERY_FAILED")
            if not batch.complete:
                return StageExecution(
                    StageStatus.BLOCKED,
                    {"attachment_discovery_evidence_refs": tuple(discovery_refs + list(batch.evidence_refs))},
                    reason="ATTACHMENT_DISCOVERY_INCOMPLETE",
                )
            discovery_refs.extend(batch.evidence_refs)
            candidates.extend(batch.candidates)

        seen_refs: set[str] = set()
        for candidate in candidates:
            try:
                candidate.__post_init__()
            except Exception:
                return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_CANDIDATE_INVALID")
            if candidate.attachment_ref in seen_refs:
                return StageExecution(StageStatus.BLOCKED, {}, reason="DUPLICATE_ATTACHMENT_REF")
            seen_refs.add(candidate.attachment_ref)
            if candidate.source_result_ref not in source_map:
                return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_SOURCE_NOT_OFFICIAL")
        if not candidates:
            return StageExecution(
                StageStatus.SUCCESS,
                {
                    "attachment_candidates": (),
                    "attachment_policy_receipts": (),
                    "approved_attachments": (),
                    "attachment_policy_state": "NO_ATTACHMENTS_FOUND",
                    "attachment_discovery_evidence_refs": tuple(discovery_refs),
                },
                evidence_refs=tuple(discovery_refs),
            )

        receipts: list[AttachmentPolicyReceipt] = []
        approved: list[ApprovedAttachment] = []
        policy_evidence: list[str] = list(discovery_refs)
        unknown = False
        candidate_by_ref = {candidate.attachment_ref: candidate for candidate in candidates}
        for candidate in candidates:
            source = source_map[candidate.source_result_ref]
            try:
                decision = evaluate_policy(candidate, source)
                if not isinstance(decision, AttachmentPolicyDecision):
                    raise ValueError("ATTACHMENT_POLICY_RESULT_INVALID")
                decision.__post_init__()
                if decision.attachment_ref != candidate.attachment_ref:
                    raise ValueError("ATTACHMENT_POLICY_REF_MISMATCH")
                if decision.status is AttachmentPolicyStatus.ALLOW:
                    parsed = urlsplit(candidate.attachment_url)
                    allowed = {host.lower().rstrip(".") for host in decision.allowed_hosts}
                    if parsed.hostname is None or parsed.hostname.lower().rstrip(".") not in allowed:
                        raise ValueError("ATTACHMENT_HOST_NOT_IN_POLICY_ALLOWLIST")
                    approved.append(ApprovedAttachment(candidate, decision))
                elif decision.status is AttachmentPolicyStatus.UNKNOWN:
                    unknown = True
                receipts.append(AttachmentPolicyReceipt(
                    attachment_ref=candidate.attachment_ref,
                    source_result_ref=candidate.source_result_ref,
                    attachment_url=candidate.attachment_url,
                    status=decision.status,
                    policy_id=decision.policy_id,
                    allowed_hosts=decision.allowed_hosts,
                    max_bytes=decision.max_bytes,
                    timeout_seconds=decision.timeout_seconds,
                    robots_required=decision.robots_required,
                    evidence_refs=decision.evidence_refs,
                    reason_code=decision.reason_code,
                ))
                policy_evidence.extend(decision.evidence_refs)
            except Exception:
                unknown = True
                receipts.append(AttachmentPolicyReceipt(
                    attachment_ref=candidate.attachment_ref,
                    source_result_ref=candidate.source_result_ref,
                    attachment_url=candidate.attachment_url,
                    status=AttachmentPolicyStatus.UNKNOWN,
                    policy_id="unknown",
                    allowed_hosts=(),
                    max_bytes=1,
                    timeout_seconds=1.0,
                    robots_required=True,
                    evidence_refs=(),
                    reason_code="ATTACHMENT_POLICY_EVALUATION_FAILED",
                ))

        output = {
            "attachment_candidates": tuple(candidates),
            "attachment_policy_receipts": tuple(receipts),
            "approved_attachments": tuple(approved),
            "attachment_policy_state": "INCOMPLETE" if unknown else "COMPLETE",
        }
        if unknown:
            return StageExecution(StageStatus.BLOCKED, output, evidence_refs=tuple(policy_evidence), reason="ATTACHMENT_POLICY_UNKNOWN")
        if not policy_evidence:
            return StageExecution(StageStatus.BLOCKED, output, reason="ATTACHMENT_POLICY_EVIDENCE_MISSING")
        return StageExecution(StageStatus.SUCCESS, output, evidence_refs=tuple(policy_evidence))

    return handler


def build_attachment_fetch_handler(
    *,
    fetcher_factory: AttachmentFetcherFactory,
    content_sink: PrivateContentSink,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    if not callable(fetcher_factory):
        raise ValueError("ATTACHMENT_FETCHER_FACTORY_REQUIRED")
    if not callable(content_sink):
        raise ValueError("PRIVATE_CONTENT_SINK_REQUIRED")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        approved = context.get("approved_attachments")
        policy_receipts = context.get("attachment_policy_receipts")
        if not isinstance(approved, Sequence) or isinstance(approved, (str, bytes, bytearray, Mapping)):
            return StageExecution(StageStatus.BLOCKED, {}, reason="APPROVED_ATTACHMENTS_MISSING")
        if not isinstance(policy_receipts, Sequence) or isinstance(policy_receipts, (str, bytes, bytearray, Mapping)):
            return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_POLICY_RECEIPTS_MISSING")
        policy_evidence = tuple(
            list(context.get("attachment_discovery_evidence_refs", ()))
            + [
                f"attachment-policy:{r.attachment_ref}:{r.policy_id}"
                for r in policy_receipts
                if isinstance(r, AttachmentPolicyReceipt) and r.evidence_refs
            ]
        )
        if not approved:
            if not policy_evidence:
                return StageExecution(StageStatus.BLOCKED, {}, reason="NO_ATTACHMENT_POLICY_EVIDENCE")
            return StageExecution(
                StageStatus.NOT_APPLICABLE,
                {
                    "attachment_fetch_receipts": (),
                    "attachment_fetch_state": "NOT_APPLICABLE",
                    "attachment_fetch_evidence_refs": policy_evidence,
                },
                evidence_refs=policy_evidence,
                reason="NO_APPROVED_ATTACHMENTS",
            )

        # Preflight every approved attachment against a typed ALLOW receipt
        # before making any network or storage call.
        policy_receipt_by_ref = {
            receipt.attachment_ref: receipt
            for receipt in policy_receipts
            if isinstance(receipt, AttachmentPolicyReceipt)
            and receipt.status is AttachmentPolicyStatus.ALLOW
            and receipt.evidence_refs
        }
        preflight: list[ApprovedAttachment] = []
        seen_approved: set[str] = set()
        for approved_item in approved:
            if not isinstance(approved_item, ApprovedAttachment):
                return StageExecution(StageStatus.BLOCKED, {}, reason="APPROVED_ATTACHMENT_INVALID")
            candidate, decision = approved_item.candidate, approved_item.policy
            try:
                candidate.__post_init__()
                decision.__post_init__()
            except Exception:
                return StageExecution(StageStatus.BLOCKED, {}, reason="APPROVED_ATTACHMENT_INVALID")
            if decision.status is not AttachmentPolicyStatus.ALLOW:
                return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_POLICY_NOT_ALLOW")
            if candidate.attachment_ref in seen_approved:
                return StageExecution(StageStatus.BLOCKED, {}, reason="DUPLICATE_APPROVED_ATTACHMENT_REF")
            seen_approved.add(candidate.attachment_ref)
            policy_receipt = policy_receipt_by_ref.get(candidate.attachment_ref)
            if (
                policy_receipt is None
                or policy_receipt.source_result_ref != candidate.source_result_ref
                or policy_receipt.attachment_url != candidate.attachment_url
                or policy_receipt.policy_id != decision.policy_id
                or policy_receipt.allowed_hosts != decision.allowed_hosts
                or policy_receipt.max_bytes != decision.max_bytes
                or policy_receipt.timeout_seconds != decision.timeout_seconds
                or policy_receipt.robots_required != decision.robots_required
            ):
                return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_POLICY_RECEIPT_MISMATCH")
            parsed_candidate = urlsplit(candidate.attachment_url)
            allowed_hosts = {host.lower().rstrip(".") for host in decision.allowed_hosts}
            if parsed_candidate.hostname is None or parsed_candidate.hostname.lower().rstrip(".") not in allowed_hosts:
                return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_HOST_NOT_ALLOWLISTED")
            preflight.append(approved_item)

        receipts: list[AttachmentFetchResult] = []
        evidence_refs: list[str] = list(policy_evidence)
        failed = False
        for approved_item in preflight:
            candidate, decision = approved_item.candidate, approved_item.policy
            policy = AttachmentPolicy(
                allowed_hosts=frozenset(decision.allowed_hosts),
                policy_allows=True,
                robots_required=decision.robots_required,
            )
            limits = AttachmentLimits(
                timeout_seconds=decision.timeout_seconds,
                max_bytes=decision.max_bytes,
            )
            try:
                fetcher = fetcher_factory(policy, limits)
                if not callable(getattr(fetcher, "fetch", None)):
                    raise ValueError("ATTACHMENT_FETCHER_INVALID")
                raw = fetcher.fetch(candidate.attachment_url)
                if not isinstance(raw, AttachmentReceipt):
                    raise ValueError("ATTACHMENT_FETCH_RECEIPT_INVALID")
                if raw.source_url != candidate.attachment_url:
                    raise ValueError("ATTACHMENT_FETCH_SOURCE_MISMATCH")
                final = urlsplit(raw.final_url)
                allowed_hosts = {host.lower().rstrip(".") for host in decision.allowed_hosts}
                if final.scheme.lower() != "https" or not final.hostname or final.username is not None or final.password is not None:
                    raise ValueError("ATTACHMENT_FINAL_URL_INVALID")
                if final.hostname.lower().rstrip(".") not in allowed_hosts:
                    raise ValueError("ATTACHMENT_FINAL_HOST_NOT_ALLOWLISTED")
                if (
                    not isinstance(raw.content, bytes)
                    or not isinstance(raw.byte_size, int)
                    or isinstance(raw.byte_size, bool)
                    or len(raw.content) != raw.byte_size
                    or raw.byte_size > decision.max_bytes
                ):
                    raise ValueError("ATTACHMENT_CONTENT_SIZE_INVALID")
                if (
                    not isinstance(raw.retrieved_at_epoch, (int, float))
                    or isinstance(raw.retrieved_at_epoch, bool)
                    or not math.isfinite(raw.retrieved_at_epoch)
                ):
                    raise ValueError("ATTACHMENT_RETRIEVAL_TIMESTAMP_INVALID")
                if not isinstance(raw.content_type, str) or not raw.content_type.strip():
                    raise ValueError("ATTACHMENT_CONTENT_TYPE_INVALID")
                if raw.media_kind not in {"pdf", "zip-container"}:
                    raise ValueError("ATTACHMENT_MEDIA_KIND_INVALID")
                digest = hashlib.sha256(raw.content).hexdigest()
                if digest != raw.sha256:
                    raise ValueError("ATTACHMENT_CONTENT_HASH_MISMATCH")
                if raw.media_kind == "pdf" and not raw.content.startswith(b"%PDF-"):
                    raise ValueError("ATTACHMENT_MEDIA_MAGIC_MISMATCH")
                if raw.media_kind == "zip-container" and not raw.content.startswith(b"PK\\x03\\x04"):
                    raise ValueError("ATTACHMENT_MEDIA_MAGIC_MISMATCH")
                content_ref = content_sink(candidate, raw)
                if not isinstance(content_ref, str) or not content_ref.strip():
                    raise ValueError("PRIVATE_CONTENT_REF_REQUIRED")
                result = AttachmentFetchResult(
                    attachment_ref=candidate.attachment_ref,
                    source_result_ref=candidate.source_result_ref,
                    source_url=raw.source_url,
                    final_url=raw.final_url,
                    content_ref=content_ref,
                    fetched_at_epoch=raw.retrieved_at_epoch,
                    content_type=raw.content_type,
                    byte_size=raw.byte_size,
                    sha256=raw.sha256,
                    media_kind=raw.media_kind,
                    status="FETCHED",
                    policy_id=decision.policy_id,
                    evidence_refs=(f"attachment-fetch:{candidate.attachment_ref}:{raw.sha256}",),
                )
                receipts.append(result)
                evidence_refs.extend(result.evidence_refs)
            except Exception:
                failed = True
                receipts.append(AttachmentFetchResult(
                    attachment_ref=candidate.attachment_ref,
                    source_result_ref=candidate.source_result_ref,
                    source_url=candidate.attachment_url,
                    final_url=None, content_ref=None, fetched_at_epoch=None,
                    content_type=None, byte_size=0, sha256=None, media_kind=None,
                    status="FAILED", policy_id=decision.policy_id,
                    evidence_refs=(), error_code="ATTACHMENT_FETCH_OR_STORE_FAILED",
                ))

        output = {
            "attachment_fetch_receipts": tuple(receipts),
            "attachment_fetch_state": "PARTIAL" if failed else "COMPLETE",
            "attachment_fetch_success_count": sum(r.status == "FETCHED" for r in receipts),
            "attachment_fetch_failure_count": sum(r.status == "FAILED" for r in receipts),
        }
        if failed:
            return StageExecution(StageStatus.BLOCKED, output, evidence_refs=tuple(evidence_refs), reason="ATTACHMENT_FETCH_INCOMPLETE")
        return StageExecution(
            StageStatus.SUCCESS, output,
            output_refs=tuple(r.content_ref for r in receipts if r.content_ref),
            evidence_refs=tuple(evidence_refs),
        )

    return handler


def build_attachment_inspection_handler(
    inspector: AttachmentInspector,
) -> Callable[[Mapping[str, Any]], StageExecution]:
    if not callable(inspector):
        raise ValueError("ATTACHMENT_INSPECTOR_REQUIRED")

    def handler(context: Mapping[str, Any]) -> StageExecution:
        fetch_state = context.get("attachment_fetch_state")
        fetched = context.get("attachment_fetch_receipts")
        if fetch_state == "NOT_APPLICABLE" and isinstance(fetched, Sequence) and not fetched:
            refs = context.get("attachment_fetch_evidence_refs", ())
            if not isinstance(refs, tuple) or not refs:
                return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_FETCH_EVIDENCE_MISSING")
            return StageExecution(
                StageStatus.NOT_APPLICABLE,
                {"attachment_inspection_receipts": (), "attachment_inspection_state": "NOT_APPLICABLE"},
                evidence_refs=refs,
                reason="NO_FETCHED_ATTACHMENTS",
            )
        if not isinstance(fetched, Sequence) or isinstance(fetched, (str, bytes, bytearray, Mapping)) or not fetched:
            return StageExecution(StageStatus.BLOCKED, {}, reason="ATTACHMENT_FETCH_RECEIPTS_MISSING")

        receipts: list[AttachmentInspectionDecision] = []
        extracted: list[AttachmentEvidenceItem] = []
        evidence_refs: list[str] = []
        incomplete = False
        for fetch_result in fetched:
            if not isinstance(fetch_result, AttachmentFetchResult) or fetch_result.status != "FETCHED" or not fetch_result.content_ref:
                incomplete = True
                continue
            try:
                decision = inspector(fetch_result.content_ref, fetch_result)
                if not isinstance(decision, AttachmentInspectionDecision):
                    raise ValueError("ATTACHMENT_INSPECTION_RESULT_INVALID")
                decision.__post_init__()
                if decision.attachment_ref != fetch_result.attachment_ref or decision.content_ref != fetch_result.content_ref:
                    raise ValueError("ATTACHMENT_INSPECTION_IDENTITY_MISMATCH")
            except Exception:
                incomplete = True
                continue
            receipts.append(decision)
            evidence_refs.extend(decision.evidence_refs)
            extracted.extend(decision.extracted_items)
            if decision.status is not AttachmentInspectionStatus.COMPLETE:
                incomplete = True

        output = {
            "attachment_inspection_receipts": tuple(receipts),
            "recruitment_evidence_candidates": tuple(extracted),
            "attachment_inspection_state": "INCOMPLETE" if incomplete else "COMPLETE",
            "attachment_inspected_count": len(receipts),
            "attachment_extracted_item_count": len(extracted),
        }
        if incomplete:
            return StageExecution(StageStatus.BLOCKED, output, evidence_refs=tuple(evidence_refs), reason="ATTACHMENT_INSPECTION_INCOMPLETE")
        if not evidence_refs:
            return StageExecution(StageStatus.BLOCKED, output, reason="ATTACHMENT_INSPECTION_EVIDENCE_MISSING")
        return StageExecution(
            StageStatus.SUCCESS, output,
            output_refs=tuple(item.evidence_ref for item in extracted),
            evidence_refs=tuple(evidence_refs),
        )

    return handler


def build_attachment_handlers(
    *,
    discover_attachments: AttachmentDiscoverer,
    evaluate_policy: AttachmentPolicyEvaluator,
    fetcher_factory: AttachmentFetcherFactory,
    content_sink: PrivateContentSink,
    inspector: AttachmentInspector,
) -> dict[str, Callable[[Mapping[str, Any]], StageExecution]]:
    return {
        "attachment_policy": build_attachment_policy_handler(discover_attachments, evaluate_policy),
        "attachment_fetch": build_attachment_fetch_handler(fetcher_factory=fetcher_factory, content_sink=content_sink),
        "attachment_inspection": build_attachment_inspection_handler(inspector),
    }
