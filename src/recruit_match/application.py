"""Public application entry point for bounded analysis runs.

The entry point composes the domain workflow with explicitly injected external
handlers. It performs no implicit network access, persistence, or mutation.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .pipeline import RunValidation
from .runner import PipelineExecution, StageExecution, execute_pipeline
from .workflow import build_analysis_contract, compose_analysis_handlers


def run_analysis(
    run_id: str,
    external_handlers: Mapping[str, Any],
    initial_context: Mapping[str, Any] | None = None,
    *,
    bounded_through: str | None = None,
) -> PipelineExecution:
    """Execute the declared workflow; missing adapters fail closed at first use.

    External handlers must return StageExecution values with evidence references
    for every stage marked evidence-required. The returned validation describes
    only the requested full or bounded run.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("RUN_ID_REQUIRED")
    if not isinstance(external_handlers, Mapping):
        raise ValueError("EXTERNAL_HANDLERS_MUST_BE_MAPPING")
    if initial_context is not None and not isinstance(initial_context, Mapping):
        raise ValueError("INITIAL_CONTEXT_MUST_BE_MAPPING")
    handlers = compose_analysis_handlers(external_handlers)
    contract = build_analysis_contract(run_id, bounded_through=bounded_through)
    return execute_pipeline(contract, handlers, initial_context)
