# Verification Stage Contracts

- Date: 2026-10-19
- Status: source present; tests authored but not executed
- Scope: identity resolution → source authority verification → currentness verification
- These modules do not perform network I/O themselves. All external detail resolvers and verifiers are injected.

## 1. Stage order

```text
Search discovery
  ↓
Identity resolution
  ↓
Source authority verification
  ↓
Currentness verification
  ↓
Attachment and recruitment-evidence stages
```

Each stage consumes the preceding stage's typed output. A search result URL is not treated as a stable opportunity identity, official source, or current recruitment notice.

## 2. Identity resolution

Module: `src/recruit_match/identity_resolution.py`

The injected identity resolver must return a typed `OpportunityIdentityDecision`. A resolved identity requires:
- stable `opportunity_id`;
- organization and position;
- recruitment-cycle identity;
- posting ID;
- identity basis and non-empty evidence references;
- a timezone-aware observation timestamp.

The stage preflights the entire input batch before invoking the resolver. Duplicate source-result references, malformed URLs, or missing discovery metadata block before resolver calls. Same opportunity ID plus identical identity fields and source URL is deduplicated with a `duplicate_of` receipt. Conflicting cycle/posting/organization/position/source URL for the same opportunity ID blocks the stage.

This is not semantic deduplication by itself. The injected resolver must obtain and justify the identity fields from traceable source evidence.

## 3. Source authority verification

Module: `src/recruit_match/source_verification.py`

The stage accepts `resolved_opportunity_sources`, not raw search results. Its injected verifier returns one of:
- `VERIFIED_OFFICIAL`;
- `VERIFIED_NON_OFFICIAL`;
- `UNKNOWN`.

A verified decision requires a verifier identity, timezone-aware observation timestamp, authority basis, and evidence references. Unknown decisions or verifier failures block the stage. Non-official sources can be classified but are not forwarded in `official_source_results`. If all results are classified but none is official, the stage can finish its classification with `COMPLETE_NO_OFFICIAL_SOURCE`; currentness verification then blocks because no official source is available.

The adapter does not infer official status from a URL suffix, page title, HTTP success, or presence of a result. The injected verifier must implement the actual authority check.

## 4. Currentness verification

Module: `src/recruit_match/currentness_verification.py`

The stage requires non-empty `official_source_results` and corresponding typed source-verification receipts whose status is `VERIFIED_OFFICIAL`, whose source URL exactly matches the opportunity source URL, and which pass receipt revalidation with evidence references and a timezone-aware observation timestamp. It rejects duplicate source-result or opportunity IDs before invoking the currentness verifier.

The verifier must return a typed `CurrentnessDecision` using the canonical `CurrentnessState` enum. Classified states require a basis and evidence references. Observation timestamps and optional deadlines must be timezone-aware. `UNKNOWN`, malformed responses, mismatched identities, or verifier exceptions block the stage.

Currentness is not eligibility, recommendation, or application readiness. `ACTIVE` or `URGENT` does not establish that the candidate satisfies mandatory requirements.

## 5. Composition

`src/recruit_match/verification_stages.py` exposes `build_verification_handlers(...)` to compose the three handlers. The caller still supplies the real resolver/verifier functions and must also configure the earlier request-scope, candidate-context, search-plan, and discovery stages.

A synthetic integration test in `tests/test_verification_stages.py` specifies a bounded `run_analysis(..., bounded_through="currentness_verification")` path. It is a test specification only; it has not been executed.

## 6. Evidence and limitations

- Typed decision objects and receipt fields provide structural contracts, not independent proof that an injected verifier is correct.
- Receipts currently exist in memory; no durable, append-only audit store or cross-process idempotency is configured.
- No live detail resolver, official-domain registry, page fetcher, or currentness verifier is configured by default.
- Test functions are authored but not executed.
- Therefore source authority, recruitment currentness, live integration, and production readiness remain unverified.
