"""In-memory orchestration for candidate-specific workflow stages.

This module deliberately has no persistence API. Candidate material, selections,
evaluations, and application progress exist only for the lifetime of the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
import uuid

from analysis_pipeline import evaluate_job_matching_payload
from job_matching_model import (
    JobRequirement, SourceDocument, retrieve_evidence_on_demand,
)


APPLICATION_STAGES = (
    "APPROVED_FOR_PREPARATION",
    "DOCUMENTS_REVIEW",
    "DOCUMENTS_DRAFTED",
    "DOCUMENTS_APPROVED",
    "APPLICATION_SUBMITTED",
    "SCREENING_RESULT_RECORDED",
    "INTERVIEW_PREPARATION",
    "INTERVIEW_COMPLETED",
    "FINAL_RESULT_RECORDED",
)


class WorkflowInputError(ValueError):
    """Invalid in-memory workflow selection or transition."""


def select_postings(postings: Iterable[dict[str, Any]], posting_ids: Iterable[str]
                    ) -> list[dict[str, Any]]:
    """Return selected postings in ledger order; reject unknown or empty IDs."""
    requested = {str(value).strip() for value in posting_ids if str(value).strip()}
    if not requested:
        raise WorkflowInputError("Select at least one posting.")
    by_id = {
        str(row.get("posting_id") or row.get("official_url")): row
        for row in postings
    }
    missing = requested - set(by_id)
    if missing:
        raise WorkflowInputError("One or more selected posting IDs are unknown.")
    return [by_id[key] for key in by_id if key in requested]


def evaluate_single_posting(*, posting: dict[str, Any],
                            requirements: Iterable[JobRequirement],
                            candidate_text: str,
                            eligibility_status: str,
                            criterion_decisions: dict[str, dict[str, Any]] | None = None,
                            min_fit_score: float = 70.0) -> dict[str, Any]:
    """Evaluate one selected posting in memory and derive an explainable hint.

    Scores and candidate text are never persisted by this function. Criterion
    decisions are supplied by the user after reviewing the retrieved snippets.
    """
    if not candidate_text.strip():
        raise WorkflowInputError("Candidate evidence is required for stage 3.")
    if isinstance(min_fit_score, bool) or not 0 <= float(min_fit_score) <= 100:
        raise WorkflowInputError("Minimum fit score must be from 0 to 100.")
    reqs = list(requirements)
    if not reqs:
        raise WorkflowInputError("At least one job requirement is required.")
    document = SourceDocument(
        document_id="session-candidate-material",
        text=candidate_text,
        source_type="user-provided-session-material",
    )
    evidence = {
        req.requirement_id: retrieve_evidence_on_demand(req, [document])
        for req in reqs
    }
    supplied_decisions = criterion_decisions or {}
    decisions = []
    for requirement in reqs:
        snippets = evidence[requirement.requirement_id]
        refs = [snippet.evidence_id for snippet in snippets]
        supplied = supplied_decisions.get(requirement.requirement_id, {})
        decision_refs = [str(value) for value in supplied.get("evidence_refs", [])]
        counter_refs = [str(value) for value in supplied.get("counter_evidence_refs", [])]
        if any(value not in refs for value in decision_refs + counter_refs):
            raise WorkflowInputError("A criterion cites evidence not retrieved for that requirement.")
        decisions.append({
            "requirement_id": requirement.requirement_id,
            "score": supplied.get("score"),
            "status": supplied.get("status", "UNASSESSED"),
            "evidence_refs": decision_refs,
            "counter_evidence_refs": counter_refs,
            "rationale": str(supplied.get("rationale", "")),
            "uncertainty_notes": list(supplied.get("uncertainty_notes", []))
            + ["USER_REVIEW_REQUIRED", f"RETRIEVED_SNIPPETS:{len(refs)}"],
        })
    payload = {
        "evaluation_id": "session-" + uuid.uuid4().hex[:12],
        "job_id": str(posting.get("posting_id") or posting.get("official_url") or ""),
        "eligibility_status": eligibility_status,
        "requirements": [{
            "requirement_id": req.requirement_id,
            "description": req.description,
            "requirement_type": req.requirement_type,
            "mandatory": req.mandatory,
            "weight": req.weight,
            "keywords": list(req.keywords),
            "target_level": req.target_level,
        } for req in reqs],
        "documents": [{
            "document_id": document.document_id,
            "text": document.text,
            "source_type": document.source_type,
        }],
        "decisions": decisions,
    }
    result = evaluate_job_matching_payload(payload)
    result_by_id = {row["requirement_id"]: row for row in result["criterion_results"]}
    mandatory_failed_ids = [
        requirement.requirement_id
        for requirement in reqs
        if requirement.mandatory
        and result_by_id[requirement.requirement_id]["status"] == "ASSESSED"
        and float(result_by_id[requirement.requirement_id]["score"]) < 3.0
    ]
    mandatory_failed = bool(mandatory_failed_ids)
    if eligibility_status == "FAIL":
        recommendation = "NOT_RECOMMENDED"
        recommendation_reason = "A required eligibility check was explicitly marked FAIL."
    elif mandatory_failed:
        recommendation = "NOT_RECOMMENDED_MANDATORY_REQUIREMENT"
        recommendation_reason = "Mandatory criteria below 3/5: " + ", ".join(mandatory_failed_ids)
    elif (eligibility_status == "PASS"
          and result["evaluation_status"] == "ASSESSED"
          and result["fit_score"] is not None
          and result["fit_score"] >= float(min_fit_score)):
        recommendation = "RECOMMENDED_FOR_USER_REVIEW"
        recommendation_reason = "Eligibility passed, required criteria passed, and the user-configured score threshold was met."
    elif result["evaluation_status"] == "ASSESSED" and result["fit_score"] is not None:
        recommendation = "NOT_RECOMMENDED_BY_USER_THRESHOLD"
        recommendation_reason = "The fully assessed score is below the user-configured minimum."
    else:
        recommendation = "HOLD_INSUFFICIENT_EVIDENCE"
        recommendation_reason = "Assessment or eligibility evidence is incomplete."
    result["recommendation"] = recommendation
    result["recommendation_reason"] = recommendation_reason
    result["recommendation_policy"] = {
        "minimum_fit_score": float(min_fit_score),
        "minimum_mandatory_criterion_score": 3.0,
        "eligibility_must_be_pass": True,
        "status": "USER_CONFIGURED_UNCALIBRATED_RULE",
    }
    # Return evidence excerpts to the active session only.
    result["evidence_records"] = [
        snippet.__dict__
        for req_snippets in evidence.values()
        for snippet in req_snippets
    ]
    return result


@dataclass
class ApplicationCase:
    """Session-only case; callers must not serialize this object."""
    posting_id: str
    status: str = "APPROVED_FOR_PREPARATION"
    events: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.posting_id.strip():
            raise WorkflowInputError("A posting ID is required for an application case.")
        self.events.append({"status": self.status, "note": "User approved preparation."})

    def advance(self, next_status: str, *, user_confirmed: bool = False,
                note: str = "") -> None:
        """Advance one step only after an explicit user-confirmed update."""
        try:
            current_index = APPLICATION_STAGES.index(self.status)
            next_index = APPLICATION_STAGES.index(next_status)
        except ValueError as exc:
            raise WorkflowInputError("Unknown application stage.") from exc
        if not user_confirmed:
            raise WorkflowInputError("User confirmation is required to advance a case.")
        if next_index != current_index + 1:
            raise WorkflowInputError("Application stages must advance one step at a time.")
        self.status = next_status
        self.events.append({"status": next_status, "note": note.strip()})
