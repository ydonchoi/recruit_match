"""Canonical analysis run contract; external adapters remain injected.

This declares the intended stage order only. It does not claim that any
external search, candidate-data provider, attachment transport, persistence
adapter, or end-to-end runtime has been configured.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
EVIDENCE_REQUIRED_STAGES = frozenset({
    "candidate_context",
    "discovery",
    "identity_resolution",
    "source_verification",
    "currentness_verification",
    "attachment_policy",
    "attachment_fetch",
    "attachment_inspection",
    "recruitment_evidence",
    "candidate_evidence_resolution",
    "revalidation",
})


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
                evidence_required=stage_id in EVIDENCE_REQUIRED_STAGES,
            )
        )
        previous = stage_id
    return RunContract(
        run_id=run_id,
        stages=tuple(specs),
        bounded_through=bounded_through,
    )



def compose_analysis_handlers(external_handlers: Mapping[str, Any]) -> dict[str, Any]:
    """Combine explicitly supplied external stage handlers with protected assessment handlers.

    Unknown stage names and attempts to override assessment handlers are rejected.
    Missing external handlers remain missing so the runner blocks at the first
    required unconfigured stage rather than silently skipping it.
    """
    from .assessment_handlers import build_assessment_handlers

    builtins = build_assessment_handlers()
    unknown = set(external_handlers) - set(ANALYSIS_STAGE_IDS)
    if unknown:
        raise ValueError(f"UNKNOWN_ANALYSIS_HANDLER:{','.join(sorted(unknown))}")
    invalid = sorted(name for name, handler in external_handlers.items() if not callable(handler))
    if invalid:
        raise ValueError(f"EXTERNAL_HANDLER_NOT_CALLABLE:{','.join(invalid)}")
    overridden = set(external_handlers) & set(builtins)
    if overridden:
        raise ValueError(f"ASSESSMENT_HANDLER_OVERRIDE_FORBIDDEN:{','.join(sorted(overridden))}")
    return {**external_handlers, **builtins}
