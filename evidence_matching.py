"""Evidence-linked job-fit assessment helpers.

Scores and evidence quality are deliberately separate. A criterion contributes
only when its cited evidence records resolve to records with a source URL and
a non-empty excerpt/observation. This is a transparent baseline, not a trained
or empirically calibrated matching model.
"""
from __future__ import annotations

from typing import Any


VALID_EVIDENCE_STRENGTH = {"E0", "E1", "E2", "E3"}


def assess_evidence_linked_fit(row: dict[str, Any]) -> dict[str, Any]:
    """Calculate a traceable weighted score from criterion-level evidence.

    Expected input:
      evidence_records: [{evidence_id, source_url, excerpt, ...}]
      requirement_evaluations: [{criterion_id, criterion, score (0..5),
        weight (>0), evidence_refs: [evidence_id], rationale?, counter_evidence_refs?}]

    Missing evidence never implies zero competence: unsupported criteria are
    excluded from the observed score and reduce evidence coverage instead.
    """
    evidence_records = row.get("evidence_records", [])
    evaluations = row.get("requirement_evaluations", [])
    if not isinstance(evidence_records, list) or not isinstance(evaluations, list):
        return {
            "score": None, "status": "INVALID_INPUT", "coverage": 0.0,
            "criterion_results": [], "missing_evidence": ["INPUTS_MUST_BE_LISTS"],
            "counter_evidence": [],
        }

    evidence_by_id: dict[str, dict[str, Any]] = {}
    for record in evidence_records:
        if not isinstance(record, dict):
            continue
        evidence_id = str(record.get("evidence_id", "")).strip()
        if evidence_id:
            evidence_by_id[evidence_id] = record

    total_weight = 0.0
    supported_weight = 0.0
    weighted_score = 0.0
    criterion_results = []
    missing_evidence = []
    counter_evidence = []

    for index, item in enumerate(evaluations):
        if not isinstance(item, dict):
            missing_evidence.append(f"criterion[{index}]:INVALID_CRITERION")
            continue
        criterion_id = str(item.get("criterion_id") or f"criterion-{index + 1}")
        label = str(item.get("criterion") or criterion_id)
        score = item.get("score")
        weight = item.get("weight")
        valid_number = (
            isinstance(score, (int, float)) and not isinstance(score, bool)
            and 0 <= score <= 5
            and isinstance(weight, (int, float)) and not isinstance(weight, bool)
            and weight > 0
        )
        if not valid_number:
            criterion_results.append({
                "criterion_id": criterion_id, "criterion": label,
                "score": None, "weight": weight if isinstance(weight, (int, float)) else None,
                "status": "INVALID_SCORE_OR_WEIGHT", "evidence_refs": [],
            })
            missing_evidence.append(f"{criterion_id}:INVALID_SCORE_OR_WEIGHT")
            continue

        total_weight += float(weight)
        refs = item.get("evidence_refs", [])
        if not isinstance(refs, list):
            refs = []
        valid_refs = []
        invalid_refs = []
        for ref in refs:
            evidence_id = str(ref).strip()
            evidence = evidence_by_id.get(evidence_id)
            if evidence and str(evidence.get("source_url", "")).strip() and str(evidence.get("excerpt", "")).strip():
                valid_refs.append(evidence_id)
            else:
                invalid_refs.append(evidence_id or "<empty>")
        counter_refs = item.get("counter_evidence_refs", [])
        if isinstance(counter_refs, list):
            for ref in counter_refs:
                evidence_id = str(ref).strip()
                if evidence_id in evidence_by_id:
                    counter_evidence.append({
                        "criterion_id": criterion_id,
                        "evidence_ref": evidence_id,
                    })

        if not valid_refs:
            status = "UNSUPPORTED"
            missing_evidence.append(f"{criterion_id}:NO_RESOLVABLE_EVIDENCE")
        else:
            status = "SUPPORTED"
            supported_weight += float(weight)
            weighted_score += float(score) * float(weight)

        criterion_results.append({
            "criterion_id": criterion_id,
            "criterion": label,
            "score": float(score),
            "weight": float(weight),
            "status": status,
            "evidence_refs": valid_refs,
            "invalid_evidence_refs": invalid_refs,
            "rationale": str(item.get("rationale", "")).strip(),
        })

    coverage = supported_weight / total_weight if total_weight else 0.0
    observed_score = (weighted_score / supported_weight * 20.0) if supported_weight else None
    if not evaluations or not total_weight:
        status = "UNASSESSED"
    elif supported_weight == 0:
        status = "UNASSESSED"
    elif supported_weight < total_weight:
        status = "PROVISIONAL"
    else:
        status = "EVIDENCE_LINKED"

    return {
        "score": round(observed_score, 2) if observed_score is not None else None,
        "status": status,
        "coverage": round(coverage, 4),
        "supported_weight": round(supported_weight, 4),
        "total_weight": round(total_weight, 4),
        "criterion_results": criterion_results,
        "missing_evidence": missing_evidence,
        "counter_evidence": counter_evidence,
    }
