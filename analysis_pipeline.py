"""Independent canonical recruitment-analysis pipeline port.

The stage order follows the legacy registry/pipeline_stages.py contract:
discovery -> opportunity state -> assessment resolution -> evidence validation ->
eligibility -> assessment -> compensation -> ranking -> top-50 -> writer gate ->
revalidation.

Services that require external evidence (state/assessment resolution and
revalidation) must be supplied by the caller. Missing required evidence is
UNKNOWN/HOLD, never silently treated as a pass. This module does not write to
an external Registry or submit applications.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Callable, Iterable
from datetime import datetime, timezone


CANONICAL_STAGE_ORDER = (
    "discovery",
    "opportunity_state_resolution",
    "assessment_resolution",
    "evidence_validation",
    "eligibility",
    "assessment",
    "compensation",
    "ranking",
    "top50",
    "writer_gate",
    "revalidation",
)


class PipelineConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    input_count: int
    output_count: int
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnalysisRunResult:
    run_id: str
    started_at: str
    ended_at: str
    status: str
    stages: tuple[StageResult, ...]
    records: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bool_verified(value: Any) -> bool:
    return value is True


def _evidence_complete(row: dict[str, Any]) -> bool:
    return bool(row.get("official_url")) and _bool_verified(row.get("decision_source_verified")) and bool(row.get("evidence_refs")) and bool(row.get("provenance_refs"))


def _writer_gate(row: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    reasons = []
    if not row.get("posting_id") and not row.get("official_url"):
        reasons.append("MISSING_STABLE_POSTING_ID")
    if not _bool_verified(row.get("authoritative_source")):
        reasons.append("AUTHORITATIVE_SOURCE_UNVERIFIED")
    if row.get("application_status") not in {"open"}:
        reasons.append("APPLICATION_STATUS_NOT_VERIFIED_OPEN")
    if not row.get("deadline_at"):
        reasons.append("DEADLINE_UNKNOWN")
    if row.get("eligibility_status") != "verified":
        reasons.append("ELIGIBILITY_NOT_VERIFIED")
    if not row.get("evidence_validation_passed"):
        reasons.append("EVIDENCE_VALIDATION_NOT_PASSED")
    if row.get("duplicate_conflict"):
        reasons.append("DUPLICATE_CONFLICT")
    if row.get("candidate_recruitment_evidence_separated") is not True:
        reasons.append("CANDIDATE_EVIDENCE_SEPARATION_NOT_CONFIRMED")
    return not reasons, tuple(reasons)


def run_analysis_pipeline(*, run_id: str, postings: Iterable[dict[str, Any]],
                          services: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
                          require_all_services: bool = True, top_n: int = 50) -> AnalysisRunResult:
    """Run the ordered analysis pipeline over observed posting records.

    External service hooks receive a copy of one posting and must return a dict.
    Hooks may enrich evidence but cannot mark a stage complete merely by being
    configured: returned data and stage invariants are checked below.
    """
    started = _now()
    services = services or {}
    records = [dict(p) for p in postings]
    stages: list[StageResult] = []
    errors: list[str] = []

    def record_stage(name: str, status: str, before: int, after: int, *notes: str) -> None:
        stages.append(StageResult(name, status, before, after, tuple(notes)))

    # Discovery: only caller-provided, observed posting records are accepted.
    before = len(records)
    records = [r for r in records if r.get("official_url") or r.get("posting_id")]
    record_stage("discovery", "COMPLETED" if len(records) else "NO_DATA", before, len(records),
                 "Uses collected records only; does not fabricate discoveries.")

    # Evidence-dependent stages fail closed if the required resolver is absent.
    for stage_name, service_key in (
        ("opportunity_state_resolution", "opportunity_state_resolution"),
        ("assessment_resolution", "assessment_resolution"),
    ):
        hook = services.get(service_key)
        if hook is None:
            note = f"MISSING_REQUIRED_SERVICE:{service_key}"
            if require_all_services:
                errors.append(note)
                for row in records:
                    row.setdefault("analysis_status", "BLOCKED")
                    row.setdefault("analysis_blockers", []).append(note)
                record_stage(stage_name, "BLOCKED", len(records), len(records), note)
            else:
                record_stage(stage_name, "UNVERIFIED", len(records), len(records), note)
            continue
        before = len(records)
        for row in records:
            try:
                enrichment = hook(dict(row))
                if not isinstance(enrichment, dict):
                    raise TypeError("service must return dict")
                row.update(enrichment)
            except Exception as exc:
                message = f"{stage_name}:{type(exc).__name__}:{exc}"
                errors.append(message)
                row.setdefault("analysis_blockers", []).append(message)
        record_stage(stage_name, "COMPLETED" if not errors else "PARTIALLY_COMPLETED", before, len(records))

    # Evidence validation: require explicit source/provenance facts.
    passed = 0
    for row in records:
        row["evidence_validation_passed"] = _evidence_complete(row) and not row.get("duplicate_conflict", False)
        if row["evidence_validation_passed"]:
            passed += 1
        else:
            row.setdefault("evidence_validation_notes", []).append("Official source, verification, evidence, or provenance is incomplete.")
    record_stage("evidence_validation", "COMPLETED", len(records), len(records),
                 f"passed={passed}", f"blocked={len(records)-passed}")

    # Eligibility remains unknown unless explicitly evidenced by an adapter/service.
    for row in records:
        if row.get("eligibility_status") not in {"verified", "partially_verified", "unverified", "not_eligible"}:
            row["eligibility_status"] = "unverified"
        if row.get("eligibility_status") != "verified":
            row["eligibility_gate"] = "HOLD"
        else:
            row["eligibility_gate"] = "PASS"
    record_stage("eligibility", "COMPLETED", len(records), len(records),
                 "No eligibility pass is inferred from missing data.")

    # Assessment uses supplied fit only; absent fit data remains unassessed.
    for row in records:
        fit = row.get("fit_assessment", "unassessed")
        row["fit_assessment"] = fit if fit in {"high", "review", "low", "unassessed"} else "unassessed"
        row["job_fit_score"] = row.get("job_fit_score") if isinstance(row.get("job_fit_score"), (int, float)) else None
    record_stage("assessment", "COMPLETED", len(records), len(records),
                 "Unprovided fit evidence remains unassessed.")

    # Compensation hierarchy: official > institutional table > public benchmark > labeled estimate.
    for row in records:
        for key, label in (
            ("official_compensation", "OFFICIAL"),
            ("institution_compensation", "INSTITUTION_TABLE"),
            ("public_benchmark_compensation", "PUBLIC_BENCHMARK"),
            ("compensation_estimate", "ESTIMATED"),
        ):
            if row.get(key):
                row["compensation_value"] = row[key]
                row["compensation_status"] = label
                break
        else:
            row["compensation_value"] = "UNKNOWN"
            row["compensation_status"] = "UNKNOWN"
    record_stage("compensation", "COMPLETED", len(records), len(records))

    # Ranking is conservative: verified eligibility first, then supplied fit score.
    def rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
        eligibility_rank = {"verified": 0, "partially_verified": 1, "unverified": 2, "not_eligible": 3}.get(row.get("eligibility_status"), 2)
        score = row.get("job_fit_score")
        score_rank = -float(score) if isinstance(score, (int, float)) else 0.0
        return (eligibility_rank, score_rank, str(row.get("institution", "")), str(row.get("title", "")))
    records.sort(key=rank_key)
    for index, row in enumerate(records, 1):
        row["rank"] = index
    record_stage("ranking", "COMPLETED", len(records), len(records))

    top_ids = {str(row.get("posting_id") or row.get("official_url")) for row in records[:max(0, top_n)]}
    for row in records:
        row["in_top_n"] = str(row.get("posting_id") or row.get("official_url")) in top_ids
    record_stage("top50", "COMPLETED", len(records), min(len(records), max(0, top_n)),
                 f"top_n={top_n}; no padding.")

    gate_pass = 0
    for row in records:
        eligible, reasons = _writer_gate(row)
        row["writer_gate"] = "READY_FOR_REVIEW" if eligible else "HOLD"
        row["writer_gate_reasons"] = list(reasons)
        gate_pass += int(eligible)
    record_stage("writer_gate", "COMPLETED", len(records), gate_pass,
                 "This gate does not write to an external Registry.")

    revalidation = services.get("revalidation")
    if revalidation is None:
        note = "MISSING_REQUIRED_SERVICE:revalidation"
        if require_all_services:
            errors.append(note)
            record_stage("revalidation", "BLOCKED", len(records), 0, note)
        else:
            record_stage("revalidation", "UNVERIFIED", len(records), len(records), note)
    else:
        failures = 0
        for row in records:
            try:
                result = revalidation(dict(row))
                if not isinstance(result, dict):
                    raise TypeError("service must return dict")
                row["revalidation"] = result
            except Exception as exc:
                failures += 1
                errors.append(f"revalidation:{type(exc).__name__}:{exc}")
        record_stage("revalidation", "COMPLETED" if not failures else "PARTIALLY_COMPLETED",
                     len(records), len(records)-failures)

    blocked_stages = any(stage.status == "BLOCKED" for stage in stages)
    status = "BLOCKED" if blocked_stages or (require_all_services and errors) else (
        "PARTIALLY_COMPLETED" if errors or any(stage.status == "UNVERIFIED" for stage in stages) else "COMPLETED"
    )
    return AnalysisRunResult(run_id, started, _now(), status, tuple(stages), tuple(records), tuple(errors))



def evaluate_job_matching_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Bridge requirement-centered matching into the canonical analysis layer.

    The payload carries job requirements, raw source documents, and explicit
    criterion decisions. It does not accept or create a normalized applicant
    profile. Criterion scores must be supplied by a human or separately
    validated assessment service; keyword retrieval alone never assigns scores.
    """
    from job_matching_model import (
        CriterionDecision, JobRequirement, SourceDocument, build_evaluation_run,
    )
    if not isinstance(payload, dict):
        raise ValueError("job matching input must be a JSON object")
    requirements_raw = payload.get("requirements", [])
    documents_raw = payload.get("documents", [])
    decisions_raw = payload.get("decisions", [])
    if not all(isinstance(value, list) for value in (requirements_raw, documents_raw, decisions_raw)):
        raise ValueError("requirements, documents, and decisions must be JSON arrays")
    requirements = []
    for item in requirements_raw:
        if not isinstance(item, dict):
            raise ValueError("each requirement must be a JSON object")
        requirements.append(JobRequirement(
            requirement_id=str(item.get("requirement_id", "")),
            description=str(item.get("description", "")),
            requirement_type=str(item.get("requirement_type", "")),
            mandatory=bool(item.get("mandatory", False)),
            weight=item.get("weight", 0.0),
            keywords=tuple(item.get("keywords", [])),
            target_level=item.get("target_level"),
        ))
    documents = []
    for item in documents_raw:
        if not isinstance(item, dict):
            raise ValueError("each source document must be a JSON object")
        documents.append(SourceDocument(
            document_id=str(item.get("document_id", "")),
            text=str(item.get("text", "")),
            source_url=str(item.get("source_url", "")),
            source_type=str(item.get("source_type", "applicant_material")),
            observed_at=str(item.get("observed_at", "")),
            content_hash=str(item.get("content_hash", "")),
        ))
    decisions = []
    for item in decisions_raw:
        if not isinstance(item, dict):
            raise ValueError("each criterion decision must be a JSON object")
        decisions.append(CriterionDecision(
            requirement_id=str(item.get("requirement_id", "")),
            score=item.get("score"),
            status=str(item.get("status", "UNASSESSED")),
            evidence_refs=tuple(item.get("evidence_refs", [])),
            counter_evidence_refs=tuple(item.get("counter_evidence_refs", [])),
            rationale=str(item.get("rationale", "")),
            uncertainty_notes=tuple(item.get("uncertainty_notes", [])),
        ))
    return build_evaluation_run(
        evaluation_id=str(payload.get("evaluation_id", "")),
        job_id=str(payload.get("job_id", "")),
        requirements=requirements,
        documents=documents,
        decisions=decisions,
        eligibility_status=str(payload.get("eligibility_status", "HOLD")),
        evaluated_at=payload.get("evaluated_at"),
    )
