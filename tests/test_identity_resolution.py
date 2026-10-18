import unittest
from types import SimpleNamespace

from recruit_match.pipeline import StageStatus
from recruit_match.search_stage import DiscoveredSearchResult
from recruit_match.identity_resolution import (
    IdentityResolutionStatus,
    OpportunityIdentityDecision,
    build_identity_resolution_handler,
)


class IdentityResolutionStageTests(unittest.TestCase):
    def result(self, result_ref="result-1", url="https://example.org/jobs/1"):
        return DiscoveredSearchResult(
            provider_id="synthetic-search",
            combination_id="matrix-A",
            provider_result_id="provider-result-1",
            title="Recruitment notice",
            source_url=url,
            observed_at="2026-10-19T12:00:00+00:00",
            query_sha256="a" * 64,
            result_ref=result_ref,
        )

    def decision(self, result, **overrides):
        values = dict(
            source_result_ref=result.result_ref,
            status=IdentityResolutionStatus.RESOLVED,
            resolver_id="synthetic-identity-resolver",
            observed_at="2026-10-19T12:01:00+00:00",
            opportunity_id="opportunity-1",
            organization="Synthetic University",
            position="Research Administrator",
            recruitment_cycle="2026-fall",
            posting_id="posting-1",
            identity_basis="Synthetic posting ID and recruitment cycle",
            evidence_refs=("synthetic:identity-evidence",),
        )
        values.update(overrides)
        return OpportunityIdentityDecision(**values)

    def handler(self, resolver):
        return build_identity_resolution_handler(
            resolver, resolver_id="fallback-identity-resolver"
        )

    def test_resolves_identity_with_cycle_posting_and_evidence(self):
        result = self.result()
        execution = self.handler(lambda item: self.decision(item))(
            {"discovered_search_results": (result,)}
        )
        self.assertEqual(execution.status, StageStatus.SUCCESS)
        source = execution.output["resolved_opportunity_sources"][0]
        self.assertEqual(source.opportunity_id, "opportunity-1")
        self.assertEqual(source.recruitment_cycle, "2026-fall")
        self.assertEqual(source.posting_id, "posting-1")
        self.assertEqual(len(execution.evidence_refs), 1)

    def test_missing_discovery_results_blocks(self):
        execution = self.handler(lambda item: self.decision(item))({})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "DISCOVERED_SEARCH_RESULTS_MISSING")

    def test_unknown_identity_blocks(self):
        execution = self.handler(lambda item: self.decision(
            item, status=IdentityResolutionStatus.UNKNOWN,
            opportunity_id=None, organization=None, position=None,
            recruitment_cycle=None, posting_id=None, identity_basis=None,
            evidence_refs=(), reason_code="DETAIL_NOT_FOUND",
        ))({"discovered_search_results": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.output["identity_resolution_unknown_count"], 1)

    def test_ambiguous_identity_blocks(self):
        execution = self.handler(lambda item: self.decision(
            item, status=IdentityResolutionStatus.AMBIGUOUS,
            reason_code="MULTIPLE_POSTING_MATCHES",
        ))({"discovered_search_results": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.output["identity_resolution_state"], "INCOMPLETE")

    def test_resolver_exception_is_sanitized(self):
        execution = self.handler(lambda item: (_ for _ in ()).throw(RuntimeError("private source body")))(
            {"discovered_search_results": (self.result(),)}
        )
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertNotIn("private source body", repr(execution.output))
        self.assertEqual(
            execution.output["identity_resolution_receipts"][0].error_code,
            "IDENTITY_RESOLUTION_FAILED",
        )

    def test_invalid_url_blocks_before_resolver_call(self):
        calls = []
        execution = self.handler(lambda item: calls.append(item) or self.decision(item))(
            {"discovered_search_results": (self.result(url="file:///etc/passwd"),)}
        )
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "DISCOVERED_SOURCE_URL_INVALID")
        self.assertEqual(calls, [])

    def test_duplicate_result_refs_block_before_resolver_call(self):
        calls = []
        execution = self.handler(lambda item: calls.append(item) or self.decision(item))(
            {"discovered_search_results": (
                self.result("same"),
                self.result("same", "https://example.org/jobs/2"),
            )}
        )
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "DUPLICATE_DISCOVERED_RESULT_REF")
        self.assertEqual(calls, [])

    def test_same_identity_same_url_is_deduplicated(self):
        first = self.result("result-1")
        second = self.result("result-2")
        execution = self.handler(lambda item: self.decision(item))(
            {"discovered_search_results": (first, second)}
        )
        self.assertEqual(execution.status, StageStatus.SUCCESS)
        self.assertEqual(execution.output["resolved_opportunity_count"], 1)
        self.assertEqual(execution.output["duplicate_source_count"], 1)
        duplicate_receipt = execution.output["identity_resolution_receipts"][1]
        self.assertEqual(duplicate_receipt.duplicate_of, "result-1")

    def test_same_opportunity_id_with_conflicting_posting_blocks(self):
        def resolver(item):
            return self.decision(
                item,
                posting_id="posting-2" if item.result_ref == "result-2" else "posting-1",
            )
        execution = self.handler(resolver)(
            {"discovered_search_results": (
                self.result("result-1"),
                self.result("result-2", "https://example.org/jobs/2"),
            )}
        )
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertTrue(execution.output["identity_conflict_detected"])
        self.assertEqual(
            execution.output["identity_resolution_receipts"][1].error_code,
            "OPPORTUNITY_IDENTITY_CONFLICT",
        )

    def test_resolved_identity_requires_recruitment_cycle_and_posting_id(self):
        with self.assertRaisesRegex(ValueError, "RESOLVED_IDENTITY_FIELDS_REQUIRED"):
            OpportunityIdentityDecision(
                source_result_ref="result",
                status=IdentityResolutionStatus.RESOLVED,
                resolver_id="resolver",
                observed_at="2026-10-19T12:01:00+00:00",
                opportunity_id="opp",
                organization="Org",
                position="Role",
                recruitment_cycle=None,
                posting_id=None,
                identity_basis="basis",
                evidence_refs=("evidence",),
            )

    def test_resolved_identity_requires_evidence(self):
        with self.assertRaisesRegex(ValueError, "RESOLVED_IDENTITY_REQUIRES_EVIDENCE"):
            OpportunityIdentityDecision(
                source_result_ref="result",
                status=IdentityResolutionStatus.RESOLVED,
                resolver_id="resolver",
                observed_at="2026-10-19T12:01:00+00:00",
                opportunity_id="opp",
                organization="Org",
                position="Role",
                recruitment_cycle="2026",
                posting_id="post",
                identity_basis="basis",
                evidence_refs=(),
            )

    def test_identity_decision_must_reference_same_result(self):
        execution = self.handler(lambda item: self.decision(
            item, source_result_ref="different-ref"
        ))({"discovered_search_results": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(
            execution.output["identity_resolution_receipts"][0].error_code,
            "IDENTITY_RESOLUTION_FAILED",
        )

    def test_naive_identity_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "IDENTITY_OBSERVED_AT_MUST_BE_AWARE"):
            OpportunityIdentityDecision(
                source_result_ref="result",
                status=IdentityResolutionStatus.UNKNOWN,
                resolver_id="resolver",
                observed_at="2026-10-19T12:01:00",
            )


if __name__ == "__main__":
    unittest.main()
