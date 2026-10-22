"""Requirement-centered job matching without a normalized applicant profile.

The module stores job requirements and per-run criterion decisions. Applicant
materials remain source documents; snippets are retrieved on demand and linked
to the evaluation run. Keyword retrieval is intentionally a transparent baseline,
not a semantic relevance or authenticity verifier.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Iterable


REQUIREMENT_TYPES = {
    "ELIGIBILITY", "CORE_SKILL", "EXPERIENCE", "TECHNICAL",
    "QUALIFICATION", "DOMAIN_KNOWLEDGE", "WORK_CONTEXT",
}
EVALUATION_STATUSES = {"ASSESSED", "PROVISIONAL", "UNASSESSED", "CONFLICTED", "INVALID_INPUT"}
ELIGIBILITY_STATUSES = {"PASS", "FAIL", "HOLD", "NOT_APPLICABLE"}


class ModelValidationError(ValueError):
    """Raised when a job requirement specification is invalid."""


@dataclass(frozen=True)
class JobRequirement:
    requirement_id: str
    description: str
    requirement_type: str
    mandatory: bool = False
    weight: float = 0.0
    keywords: tuple[str, ...] = ()
    target_level: int | None = None

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ModelValidationError("requirement_id must be non-empty")
        if not self.description.strip():
            raise ModelValidationError("description must be non-empty")
        if self.requirement_type not in REQUIREMENT_TYPES:
            raise ModelValidationError(f"unsupported requirement_type: {self.requirement_type}")
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)) or self.weight < 0:
            raise ModelValidationError("weight must be a non-negative number")
        if self.target_level is not None and (
            isinstance(self.target_level, bool) or not isinstance(self.target_level, int)
            or not 0 <= self.target_level <= 5
        ):
            raise ModelValidationError("target_level must be an integer from 0 to 5")


@dataclass(frozen=True)
class SourceDocument:
    """A source document, not a normalized applicant profile."""
    document_id: str
    text: str
    source_url: str = ""
    source_type: str = "applicant_material"
    observed_at: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class EvidenceSnippet:
    evidence_id: str
    document_id: str
    excerpt: str
    start_offset: int
    end_offset: int
    source_url: str
    source_type: str
    observed_at: str
    content_hash: str = ""


@dataclass(frozen=True)
class CriterionDecision:
    requirement_id: str
    score: float | None
    status: str
    evidence_refs: tuple[str, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()
    rationale: str = ""
    uncertainty_notes: tuple[str, ...] = ()


def _tokens(value: str) -> set[str]:
    # Basic multilingual tokenization; intentionally not a semantic model.
    return {token.casefold() for token in re.findall(r"[\w+#.-]+", value) if len(token) > 1}


def retrieve_evidence_on_demand(
    requirement: JobRequirement,
    documents: Iterable[SourceDocument],
    *,
    max_snippets: int = 5,
    context_chars: int = 240,
) -> list[EvidenceSnippet]:
    """Retrieve source excerpts relevant to one requirement only when requested.

    Matches explicit requirement keywords, or tokens from the requirement
    description when no keywords are supplied. No match is not evidence of
    missing competence. The function does not authenticate a source.
    """
    if max_snippets < 1 or context_chars < 40:
        raise ModelValidationError("max_snippets must be >= 1 and context_chars >= 40")
    terms = _tokens(" ".join(requirement.keywords) if requirement.keywords else requirement.description)
    if not terms:
        return []
    candidates: list[tuple[int, int, SourceDocument, int, int, str]] = []
    for document in documents:
        if not isinstance(document, SourceDocument) or not document.text:
            continue
        text = document.text
        for sentence_match in re.finditer(r"[^\n.!?。！？]+(?:[.!?。！？]+|$)", text):
            start, end = sentence_match.span()
            sentence = sentence_match.group().strip()
            if not sentence:
                continue
            overlap = len(terms & _tokens(sentence))
            if overlap:
                left = max(0, start - context_chars // 4)
                right = min(len(text), max(end, start + context_chars))
                excerpt = text[left:right].strip()
                candidates.append((overlap, start, document, left, right, excerpt))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2].document_id))
    snippets: list[EvidenceSnippet] = []
    seen: set[tuple[str, str]] = set()
    for _, start, doc, left, right, excerpt in candidates:
        key = (doc.document_id, excerpt)
        if key in seen:
            continue
        seen.add(key)
        snippets.append(EvidenceSnippet(
            evidence_id=f"{doc.document_id}:{left}-{right}",
            document_id=doc.document_id,
            excerpt=excerpt,
            start_offset=left,
            end_offset=right,
            source_url=doc.source_url,
            source_type=doc.source_type,
            observed_at=doc.observed_at,
            content_hash=doc.content_hash,
        ))
        if len(snippets) >= max_snippets:
            break
    return snippets


def build_evaluation_run(
    *,
    evaluation_id: str,
    job_id: str,
    requirements: Iterable[JobRequirement],
    documents: Iterable[SourceDocument],
    decisions: Iterable[CriterionDecision],
    eligibility_status: str = "HOLD",
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Persistable evaluation-run payload; applicant profile is never created."""
    reqs = list(requirements)
    docs = list(documents)
    decision_list = list(decisions)
    if not evaluation_id.strip() or not job_id.strip():
        raise ModelValidationError("evaluation_id and job_id must be non-empty")
    if eligibility_status not in ELIGIBILITY_STATUSES:
        raise ModelValidationError(f"unsupported eligibility_status: {eligibility_status}")
    req_ids = [r.requirement_id for r in reqs]
    if len(req_ids) != len(set(req_ids)):
        raise ModelValidationError("requirement_id values must be unique within a job")
    decision_ids = [d.requirement_id for d in decision_list]
    if len(decision_ids) != len(set(decision_ids)):
        raise ModelValidationError("only one final decision per requirement is allowed")
    if not set(decision_ids).issubset(set(req_ids)):
        raise ModelValidationError("decision references an unknown requirement")
    if any(d.status not in EVALUATION_STATUSES for d in decision_list):
        raise ModelValidationError("unsupported criterion evaluation status")
    if any(d.score is not None and (isinstance(d.score, bool) or not isinstance(d.score, (int, float)) or not 0 <= d.score <= 5) for d in decision_list):
        raise ModelValidationError("criterion score must be null or numeric from 0 to 5")

    req_by_id = {r.requirement_id: r for r in reqs}
    decision_by_id = {d.requirement_id: d for d in decision_list}
    evidence_by_id: dict[str, EvidenceSnippet] = {}
    for requirement in reqs:
        for snippet in retrieve_evidence_on_demand(requirement, docs):
            evidence_by_id[snippet.evidence_id] = snippet

    # Only count scores when the cited evidence exists in this run's retrieved
    # snippets. Evidence linkage does not certify truth or semantic relevance.
    total_weight = sum(float(r.weight) for r in reqs)
    supported_weight = 0.0
    weighted_score = 0.0
    criterion_results = []
    unresolved = []
    for requirement in reqs:
        decision = decision_by_id.get(requirement.requirement_id)
        if decision is None:
            criterion_results.append({
                "requirement_id": requirement.requirement_id,
                "score": None, "status": "UNASSESSED", "evidence_refs": [],
                "rationale": "", "uncertainty_notes": ["NO_DECISION_SUPPLIED"],
            })
            unresolved.append(requirement.requirement_id)
            continue
        valid_refs = [ref for ref in decision.evidence_refs if ref in evidence_by_id]
        status = decision.status
        if decision.score is not None and not valid_refs and status in {"ASSESSED", "PROVISIONAL"}:
            status = "UNASSESSED"
        if status in {"UNASSESSED", "CONFLICTED", "INVALID_INPUT"} or not valid_refs:
            unresolved.append(requirement.requirement_id)
        elif requirement.weight > 0 and decision.score is not None:
            supported_weight += float(requirement.weight)
            weighted_score += float(requirement.weight) * float(decision.score)
        criterion_results.append({
            "requirement_id": requirement.requirement_id,
            "score": decision.score if status in {"ASSESSED", "PROVISIONAL"} else None,
            "status": status,
            "evidence_refs": valid_refs,
            "counter_evidence_refs": [ref for ref in decision.counter_evidence_refs if ref in evidence_by_id],
            "rationale": decision.rationale,
            "uncertainty_notes": list(decision.uncertainty_notes),
        })

    coverage = supported_weight / total_weight if total_weight else 0.0
    fit_score = (weighted_score / supported_weight) * 20 if supported_weight else None
    all_assessed = len(criterion_results) == len(reqs) and all(
        result["status"] == "ASSESSED" and result["score"] is not None
        for result in criterion_results
    )
    if not reqs or not supported_weight:
        evaluation_status = "UNASSESSED"
    elif not all_assessed or supported_weight < total_weight:
        evaluation_status = "PROVISIONAL"
    else:
        evaluation_status = "ASSESSED"

    return {
        "evaluation_id": evaluation_id,
        "job_id": job_id,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evaluation_status": evaluation_status,
        "eligibility": {"status": eligibility_status},
        "fit_score": round(fit_score, 2) if fit_score is not None else None,
        "evidence_coverage": round(coverage, 4),
        "requirements": [asdict(r) for r in reqs],
        "criterion_results": criterion_results,
        "evidence_records": [asdict(e) for e in evidence_by_id.values()],
        "unresolved_requirements": unresolved,
        "limitations": [
            "Keyword retrieval is a baseline and may miss semantically relevant evidence.",
            "Evidence linkage does not verify authenticity, truth, or job relevance.",
            "No normalized applicant profile is created or persisted.",
        ],
    }
