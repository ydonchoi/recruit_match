import unittest
from types import SimpleNamespace

from recruit_match.pipeline import StageStatus
from recruit_match.identity_resolution import ResolvedOpportunitySource
from recruit_match.source_verification import (
    SourceAuthorityDecision,
    SourceAuthorityStatus,
    SourceVerificationReceipt,
    build_source_verification_handler,
)


class SourceVerificationStageTests(unittest.TestCase):
    def result(self, result_ref="result-1", url="https://example.org/jobs/1"):
        return ResolvedOpportunitySource(
            source_result_ref=result_ref,
            provider_id="synthetic-search",
            provider_result_id="provider-result-1",
            title="Recruitment notice",
            source_url=url,
            observed_at="2026-10-19T12:00:00+00:00",
            query_sha256="a" * 64,
            opportunity_id="opportunity-1",
            organization="Synthetic University",
            position="Research Administrator",
            recruitment_cycle="2026-fall",
            posting_id="posting-1",
            identity_basis="Synthetic identity test",
            identity_evidence_refs=("synthetic:identity",),
        )

    def official(self, result):
        return SourceAuthorityDecision(
            status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
            verifier_id="synthetic-authority-check",
            observed_at="2026-10-19T12:01:00+00:00",
            authority_basis="Synthetic test: official domain registry match",
            evidence_refs=("synthetic:authority-evidence",),
        )

    def test_official_source_is_separated_from_discovery(self):
        result = self.result()
        execution = build_source_verification_handler(
            self.official, default_verifier_id="fallback-verifier"
        )({"resolved_opportunity_sources": (result,)})
        self.assertEqual(execution.status, StageStatus.SUCCESS)
        self.assertEqual(execution.output["official_source_count"], 1)
        self.assertEqual(execution.output["official_source_results"], (result,))
        self.assertEqual(
            execution.output["source_verification_state"],
            "COMPLETE_WITH_OFFICIAL_SOURCES",
        )
        self.assertEqual(len(execution.evidence_refs), 1)

    def test_non_official_source_is_classified_but_not_forwarded(self):
        def verifier(result):
            return SourceAuthorityDecision(
                status=SourceAuthorityStatus.VERIFIED_NON_OFFICIAL,
                verifier_id="synthetic-authority-check",
                observed_at="2026-10-19T12:01:00+00:00",
                authority_basis="Synthetic test: not in official source registry",
                evidence_refs=("synthetic:nonofficial-evidence",),
            )
        execution = build_source_verification_handler(
            verifier, default_verifier_id="fallback-verifier"
        )({"resolved_opportunity_sources": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.SUCCESS)
        self.assertEqual(execution.output["official_source_count"], 0)
        self.assertEqual(execution.output["official_source_results"], ())
        self.assertEqual(
            execution.output["source_verification_state"],
            "COMPLETE_NO_OFFICIAL_SOURCE",
        )

    def test_unknown_authority_blocks_downstream(self):
        def verifier(result):
            return SourceAuthorityDecision(
                status=SourceAuthorityStatus.UNKNOWN,
                verifier_id="synthetic-authority-check",
                observed_at="2026-10-19T12:01:00+00:00",
            )
        execution = build_source_verification_handler(
            verifier, default_verifier_id="fallback-verifier"
        )({"resolved_opportunity_sources": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "SOURCE_AUTHORITY_UNKNOWN")
        self.assertEqual(execution.output["source_verification_unknown_count"], 1)

    def test_verifier_exception_is_sanitized_and_not_leaked(self):
        def verifier(result):
            raise RuntimeError("private page body")
        execution = build_source_verification_handler(
            verifier, default_verifier_id="fallback-verifier"
        )({"resolved_opportunity_sources": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertNotIn("private page body", repr(execution.output))
        receipt = execution.output["source_verification_receipts"][0]
        self.assertEqual(receipt.error_code, "SOURCE_AUTHORITY_VERIFICATION_FAILED")

    def test_invalid_verifier_return_becomes_unknown(self):
        execution = build_source_verification_handler(
            lambda result: {"official": True},
            default_verifier_id="fallback-verifier",
        )({"resolved_opportunity_sources": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.output["source_verification_unknown_count"], 1)

    def test_missing_discovered_results_blocks(self):
        execution = build_source_verification_handler(
            self.official, default_verifier_id="fallback-verifier"
        )({})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "RESOLVED_OPPORTUNITY_SOURCES_MISSING")

    def test_invalid_url_blocks_before_verifier_is_called(self):
        calls = []
        execution = build_source_verification_handler(
            lambda result: calls.append(result) or self.official(result),
            default_verifier_id="fallback-verifier",
        )({"resolved_opportunity_sources": (self.result(url="file:///etc/passwd"),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "DISCOVERED_SOURCE_URL_INVALID")
        self.assertEqual(calls, [])

    def test_duplicate_result_refs_block_before_any_verifier_call(self):
        calls = []
        execution = build_source_verification_handler(
            lambda result: calls.append(result) or self.official(result),
            default_verifier_id="fallback-verifier",
        )({"resolved_opportunity_sources": (
            self.result("same"),
            self.result("same", "https://example.org/jobs/2"),
        )})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "DUPLICATE_DISCOVERED_RESULT_REF")
        self.assertEqual(calls, [])

    def test_malformed_verified_decision_is_treated_as_unknown(self):
        decision = SourceAuthorityDecision(
            status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
            verifier_id="synthetic-authority-check",
            observed_at="2026-10-19T12:01:00+00:00",
            authority_basis="Synthetic test basis",
            evidence_refs=("synthetic:evidence",),
        )
        object.__setattr__(decision, "authority_basis", "")
        execution = build_source_verification_handler(
            lambda result: decision, default_verifier_id="fallback-verifier"
        )({"resolved_opportunity_sources": (self.result(),)})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.output["source_verification_unknown_count"], 1)

    def test_receipt_rejects_naive_observation_timestamp(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_RECEIPT_TIMESTAMP_MUST_BE_AWARE"):
            SourceVerificationReceipt(
                source_result_ref="result",
                source_url="https://example.org/job",
                status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
                verifier_id="verifier",
                observed_at="2026-10-19T12:01:00",
                authority_basis="official registry",
                evidence_refs=("evidence",),
            )

    def test_receipt_rejects_verified_status_without_evidence(self):
        with self.assertRaisesRegex(ValueError, "VERIFIED_SOURCE_REQUIRES_EVIDENCE_REFS"):
            SourceVerificationReceipt(
                source_result_ref="result",
                source_url="https://example.org/job",
                status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
                verifier_id="verifier",
                observed_at="2026-10-19T12:01:00+00:00",
                authority_basis="official registry",
                evidence_refs=(),
            )

    def test_naive_timestamp_is_rejected_at_contract_construction(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_VERIFICATION_TIMESTAMP_MUST_BE_AWARE"):
            SourceAuthorityDecision(
                status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
                verifier_id="verifier",
                observed_at="2026-10-19T12:01:00",
                authority_basis="basis",
                evidence_refs=("evidence",),
            )

    def test_verified_decision_requires_authority_basis_and_evidence(self):
        with self.assertRaisesRegex(ValueError, "VERIFIED_SOURCE_REQUIRES_AUTHORITY_BASIS"):
            SourceAuthorityDecision(
                status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
                verifier_id="verifier",
                observed_at="2026-10-19T12:01:00+00:00",
                authority_basis="",
                evidence_refs=("evidence",),
            )

    def test_unknown_result_in_mixed_batch_blocks_even_if_an_official_source_exists(self):
        results = (self.result("official"), self.result("unknown", "https://other.example/jobs/2"))
        def verifier(result):
            if result.source_result_ref == "official":
                return self.official(result)
            return SourceAuthorityDecision(
                status=SourceAuthorityStatus.UNKNOWN,
                verifier_id="synthetic-authority-check",
                observed_at="2026-10-19T12:01:00+00:00",
            )
        execution = build_source_verification_handler(
            verifier, default_verifier_id="fallback-verifier"
        )({"resolved_opportunity_sources": results})
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.output["official_source_count"], 1)
        self.assertEqual(execution.output["source_verification_unknown_count"], 1)


if __name__ == "__main__":
    unittest.main()
