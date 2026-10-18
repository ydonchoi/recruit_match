import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from recruit_match.application import run_analysis
from recruit_match.currentness_verification import CurrentnessDecision
from recruit_match.domain import CurrentnessState
from recruit_match.identity_resolution import (
    IdentityResolutionStatus,
    OpportunityIdentityDecision,
)
from recruit_match.pipeline import StageStatus
from recruit_match.runner import StageExecution
from recruit_match.search_stage import SearchProviderHit
from recruit_match.source_verification import (
    SourceAuthorityDecision,
    SourceAuthorityStatus,
)
from recruit_match.tool_call_adapter import build_tool_call_search_handlers
from recruit_match.verification_stages import build_verification_handlers


class VerificationStageCompositionTests(unittest.TestCase):
    def clock(self):
        return lambda: datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    def normalize(self, raw):
        return tuple(
            SearchProviderHit(item["id"], item["title"], item["url"])
            for item in raw["results"]
        )

    def identity_resolver(self, result):
        return OpportunityIdentityDecision(
            source_result_ref=result.result_ref,
            status=IdentityResolutionStatus.RESOLVED,
            resolver_id="synthetic-identity",
            observed_at="2026-10-19T12:01:00+00:00",
            opportunity_id="opportunity-1",
            organization="Synthetic University",
            position="Research Administrator",
            recruitment_cycle="2026-fall",
            posting_id="posting-1",
            identity_basis="Synthetic posting ID",
            evidence_refs=("synthetic:identity-evidence",),
        )

    def source_verifier(self, source):
        return SourceAuthorityDecision(
            status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
            verifier_id="synthetic-source-authority",
            observed_at="2026-10-19T12:02:00+00:00",
            authority_basis="Synthetic official source registry",
            evidence_refs=("synthetic:source-authority-evidence",),
        )

    def currentness_verifier(self, source):
        return CurrentnessDecision(
            source_result_ref=source.source_result_ref,
            opportunity_id=source.opportunity_id,
            state=CurrentnessState.ACTIVE,
            verifier_id="synthetic-currentness",
            observed_at="2026-10-19T12:03:00+00:00",
            basis="Synthetic posting status",
            evidence_refs=("synthetic:currentness-evidence",),
        )

    def test_composes_three_typed_verification_stages(self):
        handlers = build_verification_handlers(
            identity_resolver=self.identity_resolver,
            source_verifier=self.source_verifier,
            currentness_verifier=self.currentness_verifier,
            identity_resolver_id="identity",
            source_verifier_id="authority",
            currentness_verifier_id="currentness",
        )
        self.assertEqual(
            set(handlers),
            {"identity_resolution", "source_verification", "currentness_verification"},
        )

    def test_synthetic_run_connects_search_dispatch_to_currentness(self):
        combinations = (SimpleNamespace(combination_id="matrix-A", query="university admin"),)
        calls = []
        search_handlers = build_tool_call_search_handlers(
            run_id="synthetic-verification-run",
            planner=lambda context: combinations,
            dispatcher=lambda name, args: calls.append((name, args)) or {
                "results": [{
                    "id": "provider-result-1",
                    "title": "Recruitment notice",
                    "url": "https://official.example.org/jobs/1",
                }]
            },
            result_normalizer=self.normalize,
            tool_name="web.search",
            allowed_tool_names=("web.search",),
            max_planned_combinations=2,
            max_calls=1,
            clock=self.clock(),
        )
        verification_handlers = build_verification_handlers(
            identity_resolver=self.identity_resolver,
            source_verifier=self.source_verifier,
            currentness_verifier=self.currentness_verifier,
            identity_resolver_id="identity",
            source_verifier_id="authority",
            currentness_verifier_id="currentness",
        )
        handlers = {
            **search_handlers,
            **verification_handlers,
            "request_scope": lambda context: StageExecution(
                StageStatus.SUCCESS, {"user_query": "university admin"}
            ),
            "candidate_context": lambda context: StageExecution(
                StageStatus.SUCCESS, {"candidate_context_ref": "synthetic:candidate-context"},
                evidence_refs=("synthetic:candidate-context",),
            ),
        }
        result = run_analysis(
            "synthetic-verification-run",
            handlers,
            bounded_through="currentness_verification",
        )
        self.assertTrue(result.validation.valid, result.validation.issues)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [receipt.stage_id for receipt in result.receipts],
            [
                "request_scope", "candidate_context", "search_plan", "discovery",
                "identity_resolution", "source_verification", "currentness_verification",
            ],
        )
        self.assertEqual(result.context["official_source_count"], 1)
        self.assertEqual(
            result.context["currentness_by_opportunity_id"]["opportunity-1"],
            CurrentnessState.ACTIVE,
        )

    def test_unknown_identity_prevents_source_and_currentness_verification(self):
        calls = []
        def unknown_identity(result):
            calls.append("identity")
            return OpportunityIdentityDecision(
                source_result_ref=result.result_ref,
                status=IdentityResolutionStatus.UNKNOWN,
                resolver_id="identity",
                observed_at="2026-10-19T12:01:00+00:00",
                reason_code="DETAIL_NOT_FOUND",
            )
        handlers = build_verification_handlers(
            identity_resolver=unknown_identity,
            source_verifier=lambda source: calls.append("source") or self.source_verifier(source),
            currentness_verifier=lambda source: calls.append("currentness") or self.currentness_verifier(source),
            identity_resolver_id="identity",
            source_verifier_id="authority",
            currentness_verifier_id="currentness",
        )
        # Invoke the identity handler directly to verify fail-closed gating.
        from recruit_match.search_stage import DiscoveredSearchResult
        result = DiscoveredSearchResult(
            provider_id="search", combination_id="matrix-A",
            provider_result_id="result", title="Notice",
            source_url="https://example.org/job",
            observed_at="2026-10-19T12:00:00+00:00",
            query_sha256="a" * 64, result_ref="search-result-1",
        )
        execution = handlers["identity_resolution"]({"discovered_search_results": (result,)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(calls, ["identity"])

    def test_source_verification_unknown_does_not_claim_official_authority(self):
        from recruit_match.identity_resolution import ResolvedOpportunitySource
        source = ResolvedOpportunitySource(
            source_result_ref="source-1", provider_id="search",
            provider_result_id="result", source_url="https://example.org/job",
            title="Notice", observed_at="2026-10-19T12:00:00+00:00",
            query_sha256="a" * 64, opportunity_id="opp-1",
            organization="Org", position="Role", recruitment_cycle="2026",
            posting_id="post-1", identity_basis="basis",
            identity_evidence_refs=("identity-evidence",),
        )
        handlers = build_verification_handlers(
            identity_resolver=self.identity_resolver,
            source_verifier=lambda item: SourceAuthorityDecision(
                status=SourceAuthorityStatus.UNKNOWN,
                verifier_id="authority",
                observed_at="2026-10-19T12:02:00+00:00",
            ),
            currentness_verifier=self.currentness_verifier,
            identity_resolver_id="identity",
            source_verifier_id="authority",
            currentness_verifier_id="currentness",
        )
        execution = handlers["source_verification"]({"resolved_opportunity_sources": (source,)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.output["official_source_results"], ())
        self.assertEqual(execution.output["source_verification_state"], "INCOMPLETE")

    def test_currentness_is_not_called_without_verified_official_source(self):
        from recruit_match.identity_resolution import ResolvedOpportunitySource
        source = ResolvedOpportunitySource(
            source_result_ref="source-1", provider_id="search",
            provider_result_id="result", source_url="https://example.org/job",
            title="Notice", observed_at="2026-10-19T12:00:00+00:00",
            query_sha256="a" * 64, opportunity_id="opp-1",
            organization="Org", position="Role", recruitment_cycle="2026",
            posting_id="post-1", identity_basis="basis",
            identity_evidence_refs=("identity-evidence",),
        )
        called = []
        handler = build_verification_handlers(
            identity_resolver=self.identity_resolver,
            source_verifier=self.source_verifier,
            currentness_verifier=lambda item: called.append(item) or self.currentness_verifier(item),
            identity_resolver_id="identity",
            source_verifier_id="authority",
            currentness_verifier_id="currentness",
        )["currentness_verification"]
        execution = handler({
            "official_source_results": (source,),
            "source_verification_receipts": (),
        })
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "OFFICIAL_SOURCE_AUTHORITY_NOT_CONFIRMED")
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
