import unittest

from recruit_match.domain import CurrentnessState
from recruit_match.identity_resolution import ResolvedOpportunitySource
from recruit_match.pipeline import StageStatus
from recruit_match.source_verification import (
    SourceAuthorityStatus,
    SourceVerificationReceipt,
)
from recruit_match.currentness_verification import (
    CurrentnessDecision,
    build_currentness_verification_handler,
)


class CurrentnessVerificationStageTests(unittest.TestCase):
    def source(self, ref="source-1", opportunity_id="opp-1"):
        return ResolvedOpportunitySource(
            source_result_ref=ref,
            provider_id="synthetic-search",
            provider_result_id="provider-result",
            source_url="https://official.example.org/jobs/1",
            title="Recruitment notice",
            observed_at="2026-10-19T12:00:00+00:00",
            query_sha256="a" * 64,
            opportunity_id=opportunity_id,
            organization="Synthetic University",
            position="Research Administrator",
            recruitment_cycle="2026-fall",
            posting_id="posting-1",
            identity_basis="Synthetic identity",
            identity_evidence_refs=("synthetic:identity",),
        )

    def source_receipt(self, source, status=SourceAuthorityStatus.VERIFIED_OFFICIAL):
        return SourceVerificationReceipt(
            source_result_ref=source.source_result_ref,
            source_url=source.source_url,
            status=status,
            verifier_id="synthetic-source-verifier",
            observed_at="2026-10-19T12:01:00+00:00",
            authority_basis="Synthetic official-source registry",
            evidence_refs=("synthetic:authority-evidence",),
        )

    def decision(self, source, state=CurrentnessState.ACTIVE, **overrides):
        values = dict(
            source_result_ref=source.source_result_ref,
            opportunity_id=source.opportunity_id,
            state=state,
            verifier_id="synthetic-currentness-verifier",
            observed_at="2026-10-19T12:02:00+00:00",
            basis="Synthetic official page and deadline metadata",
            evidence_refs=("synthetic:currentness-evidence",),
            deadline_at=None,
        )
        values.update(overrides)
        return CurrentnessDecision(**values)

    def handler(self, verifier):
        return build_currentness_verification_handler(
            verifier, verifier_id="fallback-currentness-verifier"
        )

    def context(self, sources):
        return {
            "official_source_results": tuple(sources),
            "source_verification_receipts": tuple(self.source_receipt(source) for source in sources),
        }

    def test_active_currentness_is_recorded_with_evidence(self):
        source = self.source()
        execution = self.handler(lambda item: self.decision(item))(
            self.context((source,))
        )
        self.assertEqual(execution.status, StageStatus.SUCCESS)
        self.assertEqual(execution.output["currentness_by_opportunity_id"]["opp-1"], CurrentnessState.ACTIVE)
        self.assertEqual(execution.output["currentness_classified_count"], 1)
        self.assertEqual(len(execution.evidence_refs), 1)

    def test_closing_soon_keeps_deadline_as_separate_evidence(self):
        source = self.source()
        execution = self.handler(lambda item: self.decision(
            item, CurrentnessState.CLOSING_SOON,
            deadline_at="2026-10-25T23:59:00+09:00",
        ))(self.context((source,)))
        self.assertEqual(execution.status, StageStatus.SUCCESS)
        receipt = execution.output["currentness_receipts"][0]
        self.assertEqual(receipt.state, CurrentnessState.CLOSING_SOON)
        self.assertEqual(receipt.deadline_at, "2026-10-25T23:59:00+09:00")

    def test_unknown_currentness_blocks(self):
        source = self.source()
        execution = self.handler(lambda item: self.decision(item, CurrentnessState.UNKNOWN))(
            self.context((source,))
        )
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "CURRENTNESS_UNKNOWN")
        self.assertEqual(execution.output["currentness_unknown_count"], 1)

    def test_verifier_exception_is_sanitized(self):
        source = self.source()
        execution = self.handler(
            lambda item: (_ for _ in ()).throw(RuntimeError("private page text"))
        )(self.context((source,)))
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertNotIn("private page text", repr(execution.output))
        self.assertEqual(execution.output["currentness_receipts"][0].error_code, "CURRENTNESS_VERIFICATION_FAILED")

    def test_no_official_sources_blocks(self):
        execution = self.handler(lambda item: self.decision(item))({
            "official_source_results": (),
            "source_verification_receipts": (),
        })
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "OFFICIAL_SOURCE_RESULTS_MISSING")

    def test_missing_source_verification_receipts_blocks(self):
        source = self.source()
        execution = self.handler(lambda item: self.decision(item))({
            "official_source_results": (source,),
        })
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "SOURCE_VERIFICATION_RECEIPTS_MISSING")

    def test_nonofficial_source_receipt_cannot_authorize_currentness(self):
        source = self.source()
        execution = self.handler(lambda item: self.decision(item))({
            "official_source_results": (source,),
            "source_verification_receipts": (self.source_receipt(source, SourceAuthorityStatus.VERIFIED_NON_OFFICIAL),),
        })
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "OFFICIAL_SOURCE_AUTHORITY_NOT_CONFIRMED")

    def test_authority_receipt_for_different_url_cannot_authorize_currentness(self):
        source = self.source()
        mismatched = SourceVerificationReceipt(
            source_result_ref=source.source_result_ref,
            source_url="https://other.example.org/not-the-same-posting",
            status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
            verifier_id="synthetic-source-verifier",
            observed_at="2026-10-19T12:01:00+00:00",
            authority_basis="Synthetic official-source registry",
            evidence_refs=("synthetic:authority-evidence",),
        )
        execution = self.handler(lambda item: self.decision(item))({
            "official_source_results": (source,),
            "source_verification_receipts": (mismatched,),
        })
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "OFFICIAL_SOURCE_AUTHORITY_NOT_CONFIRMED")

    def test_untyped_source_receipt_cannot_authorize_currentness(self):
        source = self.source()
        forged = {
            "source_result_ref": source.source_result_ref,
            "status": "VERIFIED_OFFICIAL",
            "evidence_refs": ("fake-evidence",),
        }
        execution = self.handler(lambda item: self.decision(item))({
            "official_source_results": (source,),
            "source_verification_receipts": (forged,),
        })
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "OFFICIAL_SOURCE_AUTHORITY_NOT_CONFIRMED")

    def test_duplicate_source_refs_block_before_verifier(self):
        source = self.source()
        calls = []
        execution = self.handler(lambda item: calls.append(item) or self.decision(item))(
            self.context((source, source))
        )
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "DUPLICATE_OFFICIAL_SOURCE_REF")
        self.assertEqual(calls, [])

    def test_duplicate_opportunity_ids_block_before_verifier(self):
        first, second = self.source("source-1"), self.source("source-2")
        calls = []
        execution = self.handler(lambda item: calls.append(item) or self.decision(item))(
            self.context((first, second))
        )
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.reason, "DUPLICATE_OFFICIAL_OPPORTUNITY_ID")
        self.assertEqual(calls, [])

    def test_mismatched_decision_identity_becomes_unknown(self):
        source = self.source()
        execution = self.handler(lambda item: self.decision(
            item, opportunity_id="different-opportunity"
        ))(self.context((source,)))
        self.assertEqual(execution.status, StageStatus.BLOCKED)
        self.assertEqual(execution.output["currentness_unknown_count"], 1)

    def test_naive_timestamp_is_rejected(self):
        source = self.source()
        with self.assertRaisesRegex(ValueError, "CURRENTNESS_OBSERVED_AT_MUST_BE_AWARE"):
            self.decision(source, observed_at="2026-10-19T12:02:00")

    def test_classified_state_requires_basis_and_evidence(self):
        source = self.source()
        with self.assertRaisesRegex(ValueError, "CLASSIFIED_CURRENTNESS_REQUIRES_BASIS"):
            self.decision(source, basis="", evidence_refs=("evidence",))

    def test_string_state_is_rejected(self):
        source = self.source()
        with self.assertRaisesRegex(ValueError, "CURRENTNESS_STATE_INVALID"):
            self.decision(source, state="ACTIVE")


if __name__ == "__main__":
    unittest.main()
