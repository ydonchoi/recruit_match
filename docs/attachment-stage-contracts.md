# Attachment Stage Contracts

- Date: 2026-10-19
- Status: implementation source present; test functions authored, not executed
- Scope: attachment discovery → policy decision → bounded fetch → private content storage → inspection evidence

## 1. Stage boundary

```text
Verified official source + currentness result
  ↓
Attachment discovery (injected)
  ↓
Attachment policy (allow / deny / unknown)
  ↓
Bounded fetch (existing SafeAttachmentFetcher contract)
  ↓
Private content sink (required; raw bytes never enter pipeline context)
  ↓
Inspection adapter (injected parser / isolated worker)
  ↓
Requirement-level recruitment evidence candidates
```

The adapter module does not select hosts, fetcher implementations, storage backends, or parsers by default. All external operations are explicitly injected.

## 2. Attachment policy

Module: `src/recruit_match/attachment_stages.py`

The policy stage requires identity-resolved sources and typed `SourceVerificationReceipt` records whose status is `VERIFIED_OFFICIAL` and whose URL matches the source record. An injected discovery adapter must return an `AttachmentDiscoveryBatch` with a completeness flag and evidence references.

Each candidate must have a stable attachment reference, parent source reference, absolute HTTPS URL without credentials, and link evidence. The policy evaluator returns `ALLOW`, `DENY`, or `UNKNOWN`:
- ALLOW requires a non-empty explicit host allowlist, positive byte limit, finite positive timeout, and evidence references. The attachment hostname must be in the allowlist.
- DENY requires evidence and a reason code. The candidate is retained in the policy receipts but is not fetched.
- UNKNOWN or malformed policy output blocks the stage. No attachment is fetched.

An explicitly complete scan with no attachments is a successful policy stage with `NO_ATTACHMENTS_FOUND`, supported by scan evidence.

## 3. Bounded fetch and private storage

The fetch stage requires both an injected fetcher factory and an injected private content sink. The sink is mandatory; there is no default repository or GitHub storage path.

For every approved attachment, the adapter:
- passes a typed `AttachmentPolicy` and `AttachmentLimits` to the fetcher factory;
- validates that the returned receipt belongs to the requested URL;
- validates the final URL is HTTPS and its hostname remains allowlisted;
- checks byte count, maximum size, media kind, content type, finite retrieval timestamp, and SHA-256 integrity;
- sends bytes to the private sink only after validation;
- requires the sink to return a non-empty content reference;
- returns metadata and the content reference, never raw document bytes, to the pipeline context.

The existing `SafeAttachmentFetcher` is the intended safe transport implementation. Its actual DNS pinning, redirects, TLS, robots handling, and byte-limit behavior still require runtime tests. The stage adapter itself does not perform network calls unless the caller injects and invokes a fetcher.

The content sink should provide idempotent storage or a reconciliation path for an ambiguous sink outcome. The adapter does not automatically retry after a fetch/store exception; an orphaned stored object may require explicit reconciliation.

When no attachment is approved, the fetch stage returns `NOT_APPLICABLE` with policy evidence. The workflow explicitly permits this state for the fetch stage.

## 4. Inspection and requirement evidence

The inspection stage receives only content references and fetch metadata. An injected inspector must load the content through the authorized storage boundary and return a typed `AttachmentInspectionDecision`.

A complete decision includes a timezone-aware observation timestamp and evidence references. Each extracted item must include:
- evidence ID;
- requirement text;
- requirement kind (mandatory, preferred, compensation, application document, or other);
- source location (for example, PDF page and section);
- evidence reference.

An incomplete or unknown inspection blocks downstream processing. The adapter never claims that an attachment was semantically inspected merely because it was downloaded. Parser isolation, archive-entry limits, expanded-size limits, OCR quality thresholds, and semantic extraction remain the responsibility of the injected inspector and are not implemented here.

If there are no approved/fetched attachments, inspection returns `NOT_APPLICABLE` only when fetch-stage evidence is present.

## 5. Evidence and limitations

- `build_attachment_handlers(...)` composes `attachment_policy`, `attachment_fetch`, and `attachment_inspection` for injection into `run_analysis()`.
- `tests/test_attachment_stages.py` contains 15 test functions covering policy gating, official-source provenance, no-attachment handling, hash/redirect checks, private sink behavior, and requirement-level inspection evidence. They are authored only, not executed.
- No attachment discoverer, policy evaluator, private sink, or parser is configured by default.
- No candidate data or raw attachment bytes are written to the repository.
- Therefore live fetching, storage durability, parser isolation, extraction quality, and production readiness remain **UNVERIFIED**.
