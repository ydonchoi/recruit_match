"""Canonical analysis run contract; external adapters remain injected.

This declares the intended stage order only. It does not claim that any
external search, candidate-data provider, attachment transport, persistence
adapter, or end-to-end runtime has been configured.
"""
from __future__ import annotations

from .pipeline import RunContract, StageSpec


ANALYSIS_STAGE_IDS = (
    "request_scope",
    "candidate_context",
    "search_plan",
    "discovery",
    "identity_resolution",
    "source_verification",
    "currentness_verification",
    "attachment_policy",
    "attachment_fetch",
    "attachment_inspection",
    "recruitment_evidence",
    "candidate_evidence_resolution",
    "eligibility",
    "fit_assessment",
    "compensation_resolution",
    "revalidation",
    "ranking",
    "recommendation",
)

ATTACHMENT_OPTIONAL_STAGES = frozenset({"attachment_fetch", "attachment_inspection"})


def build_analysis_contract(run_id: str, *, bounded_through: str | None = None) -> RunContract:
    """Create a sequential, bounded analysis contract without side effects."""
    specs = []
    previous = None
    for stage_id in ANALYSIS_STAGE_IDS:
        predecessors = () if previous is None else (previous,)
        specs.append(
            StageSpec(
                stage_id=stage_id,
                required=True,
                allow_not_applicable=stage_id in ATTACHMENT_OPTIONAL_STAGES,
                predecessors=predecessors,
            )
        )
        previous = stage_id
    return RunContract(
        run_id=run_id,
        stages=tuple(specs),
        bounded_through=bounded_through,
    )
