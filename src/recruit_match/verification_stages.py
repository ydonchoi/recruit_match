"""Composition helpers for identity, source-authority, and currentness stages."""

from collections.abc import Callable
from typing import Any

from .currentness_verification import (
    CurrentnessDecision,
    build_currentness_verification_handler,
)
from .identity_resolution import (
    OpportunityIdentityDecision,
    build_identity_resolution_handler,
)
from .source_verification import (
    SourceAuthorityDecision,
    build_source_verification_handler,
)


def build_verification_handlers(
    *,
    identity_resolver: Callable[[Any], OpportunityIdentityDecision],
    source_verifier: Callable[[Any], SourceAuthorityDecision],
    currentness_verifier: Callable[[Any], CurrentnessDecision],
    identity_resolver_id: str,
    source_verifier_id: str,
    currentness_verifier_id: str,
) -> dict[str, Callable]:
    """Compose the three sequential verification stages from injected adapters.

    These factories do not perform network I/O themselves. Each injected
    resolver/verifier is responsible for its actual evidence collection and
    must return the typed, evidence-backed decision required by its contract.
    """
    return {
        "identity_resolution": build_identity_resolution_handler(
            identity_resolver, resolver_id=identity_resolver_id
        ),
        "source_verification": build_source_verification_handler(
            source_verifier, default_verifier_id=source_verifier_id
        ),
        "currentness_verification": build_currentness_verification_handler(
            currentness_verifier, verifier_id=currentness_verifier_id
        ),
    }
