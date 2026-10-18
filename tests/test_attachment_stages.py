import hashlib
import unittest
from types import SimpleNamespace

from recruit_match.attachments import AttachmentReceipt
from recruit_match.attachment_stages import (
    AttachmentCandidate,
    AttachmentDiscoveryBatch,
    AttachmentEvidenceItem,
    AttachmentInspectionDecision,
    AttachmentInspectionStatus,
    AttachmentPolicyDecision,
    AttachmentPolicyReceipt,
    AttachmentPolicyStatus,
    ApprovedAttachment,
    build_attachment_fetch_handler,
    build_attachment_inspection_handler,
    build_attachment_policy_handler,
)
from recruit_match.identity_resolution import ResolvedOpportunitySource
from recruit_match.pipeline import StageStatus
from recruit_match.source_verification import (
    SourceAuthorityStatus,
    SourceVerificationReceipt,
)


class AttachmentStageTests(unittest.TestCase):
    def source(self):
        return ResolvedOpportunitySource(
            source_result_ref="source-1",
            provider_id="synthetic-search",
            provider_result_id="provider-result",
            source_url="https://official.example.org/jobs/1",
            title="Recruitment notice",
            observed_at="2026-10-19T12:00:00+00:00",
            query_sha256="a" * 64,
            opportunity_id="opp-1",
            organization="Synthetic University",
            position="Research Administrator",
            recruitment_cycle="2026-fall",
            posting_id="posting-1",
            identity_basis="Synthetic posting identity",
            identity_evidence_refs=("synthetic:identity",),
        )

    def source_receipt(self):
        return SourceVerificationReceipt(
            source_result_ref="source-1",
            source_url="https://official.example.org/jobs/1",
            status=SourceAuthorityStatus.VERIFIED_OFFICIAL,
            verifier_id="synthetic-authority",
            observed_at="2026-10-19T12:01:00+00:00",
            authority_basis="Synthetic official source registry",
            evidence_refs=("synthetic:official-source",),
        )

    def candidate(self, url="https://official.example.org/files/job.pdf"):
        return AttachmentCandidate(
            attachment_ref="attachment-1",
            source_result_ref="source-1",
            attachment_url=url,
            link_evidence_refs=("synthetic:attachment-link",),
        )

    def batch(self, candidates=None, complete=True):
        return AttachmentDiscoveryBatch(
            source_result_ref="source-1",
            complete=complete,
            candidates=tuple(candidates or ()),
            evidence_refs=("synthetic:attachment-scan",),
        )

    def allow(self, candidate=None, **overrides):
        candidate = candidate or self.candidate()
        values = dict(
            attachment_ref=candidate.attachment_ref,
            status=AttachmentPolicyStatus.ALLOW,
            policy_id="test-policy-v1",
            allowed_hosts=("official.example.org",),
            max_bytes=1024 * 1024,
            timeout_seconds=2.0,
            robots_required=False,
            evidence_refs=("synthetic:attachment-policy",),
        )
        values.update(overrides)
        return AttachmentPolicyDecision(**values)

    def policy_receipt(self, candidate, decision):
        return AttachmentPolicyReceipt(
            attachment_ref=candidate.attachment_ref,
            source_result_ref=candidate.source_result_ref,
            attachment_url=candidate.attachment_url,
            status=AttachmentPolicyStatus.ALLOW,
            policy_id=decision.policy_id,
            allowed_hosts=decision.allowed_hosts,
            max_bytes=decision.max_bytes,
            timeout_seconds=decision.timeout_seconds,
            robots_required=decision.robots_required,
            evidence_refs=decision.evidence_refs,
        )

    def context(self, candidates=None):
        return {
            "official_source_results": (self.source(),),
            "source_verification_receipts": (self.source_receipt(),),
        }

    def test_attachment_policy_allows_only_allowlisted_host(self):
        candidate = self.candidate()
        handler = build_attachment_policy_handler(
            lambda source: self.batch((candidate,)),
            lambda item, source: self.allow(item),
        )
        result = handler(self.context())
        self.assertEqual(result.status, StageStatus.SUCCESS)
        self.assertEqual(len(result.output["approved_attachments"]), 1)
        self.assertEqual(result.output["attachment_policy_state"], "COMPLETE")

    def test_attachment_policy_rejects_allow_decision_with_non_allowlisted_host(self):
        candidate = self.candidate()
        handler = build_attachment_policy_handler(
            lambda source: self.batch((candidate,)),
            lambda item, source: self.allow(item, allowed_hosts=("other.example.org",)),
        )
        result = handler(self.context())
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "ATTACHMENT_POLICY_UNKNOWN")

    def test_attachment_policy_unknown_blocks(self):
        candidate = self.candidate()
        def evaluator(item, source):
            return AttachmentPolicyDecision(
                attachment_ref=item.attachment_ref,
                status=AttachmentPolicyStatus.UNKNOWN,
                policy_id="test-policy",
                allowed_hosts=(),
                max_bytes=1024,
                timeout_seconds=1.0,
                robots_required=True,
                evidence_refs=(),
            )
        result = build_attachment_policy_handler(
            lambda source: self.batch((candidate,)), evaluator
        )(self.context())
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.output["attachment_policy_state"], "INCOMPLETE")

    def test_attachment_policy_denial_is_recorded_without_fetch_approval(self):
        candidate = self.candidate()
        def evaluator(item, source):
            return AttachmentPolicyDecision(
                attachment_ref=item.attachment_ref,
                status=AttachmentPolicyStatus.DENY,
                policy_id="test-policy",
                allowed_hosts=(),
                max_bytes=1024,
                timeout_seconds=1.0,
                robots_required=True,
                evidence_refs=("synthetic:deny-evidence",),
                reason_code="HOST_NOT_APPROVED",
            )
        result = build_attachment_policy_handler(
            lambda source: self.batch((candidate,)), evaluator
        )(self.context())
        self.assertEqual(result.status, StageStatus.SUCCESS)
        self.assertEqual(result.output["approved_attachments"], ())
        self.assertEqual(result.output["attachment_policy_receipts"][0].status, AttachmentPolicyStatus.DENY)

    def test_no_attachments_is_explicitly_recorded(self):
        result = build_attachment_policy_handler(
            lambda source: self.batch(()),
            lambda item, source: self.allow(item),
        )(self.context())
        self.assertEqual(result.status, StageStatus.SUCCESS)
        self.assertEqual(result.output["attachment_policy_state"], "NO_ATTACHMENTS_FOUND")
        self.assertTrue(result.evidence_refs)

    def test_attachment_policy_requires_verified_official_source_receipt(self):
        calls = []
        context = self.context()
        context["source_verification_receipts"] = ()
        result = build_attachment_policy_handler(
            lambda source: calls.append(source) or self.batch(()),
            lambda item, source: self.allow(item),
        )(context)
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "OFFICIAL_SOURCE_AUTHORITY_NOT_CONFIRMED")
        self.assertEqual(calls, [])

    def test_incomplete_attachment_scan_blocks(self):
        candidate = self.candidate()
        result = build_attachment_policy_handler(
            lambda source: self.batch((candidate,), complete=False),
            lambda item, source: self.allow(item),
        )(self.context())
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "ATTACHMENT_DISCOVERY_INCOMPLETE")

    def test_no_attachment_scan_propagates_not_applicable_through_all_stages(self):
        policy = build_attachment_policy_handler(
            lambda source: self.batch(()),
            lambda item, source: self.allow(item),
        )(self.context())
        self.assertEqual(policy.status, StageStatus.SUCCESS)
        fetched = build_attachment_fetch_handler(
            fetcher_factory=lambda policy, limits: None,
            content_sink=lambda candidate, receipt: "unused",
        )({
            **policy.output,
            "attachment_policy_receipts": policy.output["attachment_policy_receipts"],
        })
        self.assertEqual(fetched.status, StageStatus.NOT_APPLICABLE)
        inspected = build_attachment_inspection_handler(lambda ref, metadata: None)({
            **fetched.output,
        })
        self.assertEqual(inspected.status, StageStatus.NOT_APPLICABLE)
        self.assertTrue(inspected.evidence_refs)

    def test_fetch_and_inspection_do_not_put_raw_bytes_in_pipeline_context(self):
        candidate = self.candidate()
        decision = self.allow(candidate)
        approved = ApprovedAttachment(candidate, decision)
        content = b"%PDF-1.4\nsynthetic public job posting"
        digest = hashlib.sha256(content).hexdigest()
        raw = AttachmentReceipt(
            source_url=candidate.attachment_url,
            final_url=candidate.attachment_url,
            retrieved_at_epoch=1792411200.0,
            content_type="application/pdf",
            byte_size=len(content),
            sha256=digest,
            media_kind="pdf",
            content=content,
        )
        stored = []
        fetch_handler = build_attachment_fetch_handler(
            fetcher_factory=lambda policy, limits: SimpleNamespace(fetch=lambda url: raw),
            content_sink=lambda item, receipt: stored.append(receipt.content) or "private://attachment-1",
        )
        fetched = fetch_handler({
            "approved_attachments": (approved,),
            "attachment_policy_receipts": (self.policy_receipt(candidate, decision),),
        })
        self.assertEqual(fetched.status, StageStatus.SUCCESS)
        self.assertEqual(stored, [content])
        self.assertNotIn(content, repr(fetched.context if hasattr(fetched, "context") else fetched.output))
        fetch_result = fetched.output["attachment_fetch_receipts"][0]
        self.assertEqual(fetch_result.content_ref, "private://attachment-1")
        self.assertFalse(hasattr(fetch_result, "content"))

    def test_fetch_rejects_approved_attachment_without_matching_policy_receipt(self):
        candidate = self.candidate()
        decision = self.allow(candidate)
        calls = []
        result = build_attachment_fetch_handler(
            fetcher_factory=lambda policy, limits: calls.append("fetch") or None,
            content_sink=lambda item, receipt: "private://attachment",
        )({
            "approved_attachments": (ApprovedAttachment(candidate, decision),),
            "attachment_policy_receipts": (),
        })
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "ATTACHMENT_POLICY_RECEIPT_MISMATCH")
        self.assertEqual(calls, [])

    def test_fetch_blocks_when_private_content_sink_fails(self):
        candidate = self.candidate()
        decision = self.allow(candidate)
        content = b"%PDF-1.4\ncontent"
        raw = AttachmentReceipt(
            source_url=candidate.attachment_url, final_url=candidate.attachment_url,
            retrieved_at_epoch=1792411200.0, content_type="application/pdf",
            byte_size=len(content), sha256=hashlib.sha256(content).hexdigest(),
            media_kind="pdf", content=content,
        )
        result = build_attachment_fetch_handler(
            fetcher_factory=lambda policy, limits: SimpleNamespace(fetch=lambda url: raw),
            content_sink=lambda item, receipt: (_ for _ in ()).throw(RuntimeError("private storage failure")),
        )({
            "approved_attachments": (ApprovedAttachment(candidate, decision),),
            "attachment_policy_receipts": (self.policy_receipt(candidate, decision),),
        })
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.output["attachment_fetch_failure_count"], 1)
        self.assertNotIn("private storage failure", repr(result.output))

    def test_fetch_rejects_content_hash_mismatch_before_storage(self):
        candidate = self.candidate()
        decision = self.allow(candidate)
        content = b"%PDF-1.4\\ncontent"
        raw = AttachmentReceipt(
            source_url=candidate.attachment_url, final_url=candidate.attachment_url,
            retrieved_at_epoch=1792411200.0, content_type="application/pdf",
            byte_size=len(content), sha256="0" * 64,
            media_kind="pdf", content=content,
        )
        stored = []
        result = build_attachment_fetch_handler(
            fetcher_factory=lambda policy, limits: SimpleNamespace(fetch=lambda url: raw),
            content_sink=lambda item, receipt: stored.append(receipt.content) or "private://attachment-1",
        )({
            "approved_attachments": (ApprovedAttachment(candidate, decision),),
            "attachment_policy_receipts": (self.policy_receipt(candidate, decision),),
        })
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.output["attachment_fetch_failure_count"], 1)
        self.assertEqual(stored, [])

    def test_fetch_rejects_redirect_to_host_outside_policy(self):
        candidate = self.candidate()
        decision = self.allow(candidate)
        content = b"%PDF-1.4\ncontent"
        raw = AttachmentReceipt(
            source_url=candidate.attachment_url, final_url="https://evil.example.net/job.pdf",
            retrieved_at_epoch=1792411200.0, content_type="application/pdf",
            byte_size=len(content), sha256=hashlib.sha256(content).hexdigest(),
            media_kind="pdf", content=content,
        )
        result = build_attachment_fetch_handler(
            fetcher_factory=lambda policy, limits: SimpleNamespace(fetch=lambda url: raw),
            content_sink=lambda item, receipt: "private://attachment-1",
        )({
            "approved_attachments": (ApprovedAttachment(candidate, decision),),
            "attachment_policy_receipts": (self.policy_receipt(candidate, decision),),
        })
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.output["attachment_fetch_receipts"][0].error_code, "ATTACHMENT_FETCH_OR_STORE_FAILED")

    def test_no_approved_attachments_returns_not_applicable_with_evidence(self):
        receipt = AttachmentPolicyReceipt(
            attachment_ref="attachment-1",
            source_result_ref="source-1",
            attachment_url="https://official.example.org/files/job.pdf",
            status=AttachmentPolicyStatus.DENY,
            policy_id="test-policy",
            allowed_hosts=(),
            max_bytes=1024,
            timeout_seconds=1.0,
            robots_required=True,
            evidence_refs=("synthetic:denied",),
            reason_code="HOST_NOT_APPROVED",
        )
        result = build_attachment_fetch_handler(
            fetcher_factory=lambda policy, limits: None,
            content_sink=lambda candidate, receipt: "unused",
        )({"approved_attachments": (), "attachment_policy_receipts": (receipt,)})
        self.assertEqual(result.status, StageStatus.NOT_APPLICABLE)
        self.assertTrue(result.evidence_refs)
        inspection = build_attachment_inspection_handler(lambda ref, meta: None)({
            **result.output,
            "attachment_fetch_evidence_refs": result.evidence_refs,
        })
        self.assertEqual(inspection.status, StageStatus.NOT_APPLICABLE)

    def test_inspection_returns_requirement_level_evidence(self):
        item = AttachmentEvidenceItem(
            evidence_id="evidence-1",
            requirement_text="Applicants must hold a relevant degree",
            requirement_kind="MANDATORY",
            source_location="PDF page 2, qualification section",
            evidence_ref="private://evidence-1",
        )
        fetch_result = SimpleNamespace(
            attachment_ref="attachment-1", content_ref="private://attachment-1",
            status="FETCHED",
        )
        decision = AttachmentInspectionDecision(
            attachment_ref="attachment-1",
            content_ref="private://attachment-1",
            status=AttachmentInspectionStatus.COMPLETE,
            inspector_id="synthetic-inspector",
            observed_at="2026-10-19T12:05:00+00:00",
            evidence_refs=("synthetic:inspection-evidence",),
            extracted_items=(item,),
        )
        result = build_attachment_inspection_handler(lambda ref, metadata: decision)({
            "attachment_fetch_state": "COMPLETE",
            "attachment_fetch_receipts": (fetch_result,),
        })
        self.assertEqual(result.status, StageStatus.SUCCESS)
        self.assertEqual(result.output["attachment_extracted_item_count"], 1)
        self.assertEqual(result.output["recruitment_evidence_candidates"][0].evidence_ref, "private://evidence-1")

    def test_incomplete_inspection_blocks_downstream(self):
        fetch_result = SimpleNamespace(
            attachment_ref="attachment-1", content_ref="private://attachment-1",
            status="FETCHED",
        )
        decision = AttachmentInspectionDecision(
            attachment_ref="attachment-1",
            content_ref="private://attachment-1",
            status=AttachmentInspectionStatus.INCOMPLETE,
            inspector_id="synthetic-inspector",
            observed_at="2026-10-19T12:05:00+00:00",
            evidence_refs=("synthetic:inspection-evidence",),
            limitations=("OCR confidence below threshold",),
        )
        result = build_attachment_inspection_handler(lambda ref, metadata: decision)({
            "attachment_fetch_state": "COMPLETE",
            "attachment_fetch_receipts": (fetch_result,),
        })
        self.assertEqual(result.status, StageStatus.BLOCKED)
        self.assertEqual(result.reason, "ATTACHMENT_INSPECTION_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
