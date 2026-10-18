# External Adapter Contracts

Status: **INTERFACE POLICY / NO LIVE PROVIDERS CONFIGURED**

This document specifies the boundary for adapters needed by the 18-stage workflow. It does not assert that any provider is authorized, available, connected, or tested. The public entry point is `src/recruit_match/application.py`; all external handlers are injected and missing handlers block execution.

## Required adapter groups

| Workflow stages | Adapter responsibility | Required outputs | Fail-closed condition |
|---|---|---|---|
| `request_scope`, `search_plan` | Validate user intent, scope and search plan without claiming a search occurred | Normalized request, plan version, bounded-run intent | Missing scope or invalid plan |
| `candidate_context` | Read minimum necessary candidate facts from an approved private source | Versioned candidate-context reference, privacy decision, schema decision | No approved source, excess fields, unresolved access/privacy decision |
| `discovery` | Execute an authorized search query against an approved provider | Provider identity, query/combination ID, observation time, result references, retrieval status | Provider unavailable, no attributable retrieval receipt, or unapproved provider |
| `identity_resolution` | Resolve stable opportunity/posting identity and duplicate conflicts | Stable IDs, recruitment-cycle identity, duplicate state, conflict references | Ambiguous identity or unresolved duplicate conflict |
| `source_verification`, `currentness_verification` | Verify official source identity and current status independently of discovery | Source URL, source authority basis, observed time, verification state, currentness state | Source authority or currentness unknown |
| `attachment_policy`, `attachment_fetch`, `attachment_inspection` | Apply explicit host/policy gate, fetch within bounds, inspect and record integrity | Policy decision, fetch receipt, size/type/hash, inspection result | Policy denied, unsafe transport, limit exceeded, parser result unknown |
| `recruitment_evidence` | Extract decision-relevant requirements from official recruitment materials | Requirement-level evidence references, source location, extraction status | No traceable source evidence |
| `candidate_evidence_resolution` | Match minimum necessary candidate evidence to each requirement | Candidate evidence references, verification status, unresolved gaps | Missing/unauthorized candidate evidence or unsupported inference |
| `revalidation` | Recheck source/currentness and invalidation triggers before recommendation | Revalidation timestamp, changed fields, decision invalidation status | Stale or changed source not reconciled |

Pure assessment stages (`eligibility`, `fit_assessment`, `compensation_resolution`, `ranking`, `recommendation`) are implemented as deterministic domain functions and are protected from external-handler overrides. `src/recruit_match/search_stage.py` now provides injected `search_plan` and `discovery` stage-handler factories. `build_search_handlers(...)` returns the pair to pass to `run_analysis()` alongside request-scope and candidate-context handlers.

## Search call budget and execution receipts

`src/recruit_match/search_execution.py` defines a provider-neutral bridge from Search Matrix-like objects (stable `combination_id` and `query`) to a budgeted callable. For each planned combination it emits one receipt with the ordinal, combination ID, attempted/not-attempted flag, status, result count, and a sanitized error code when the call fails.

The report enforces these accounting invariants:

- `planned_query_count = attempted_call_count + skipped_query_count`;
- `attempted_call_count = successful_call_count + failed_call_count`;
- `attempted_call_count <= max_calls`;
- exactly one receipt exists for every planned combination;
- duplicate plan ordinals or stable combination IDs are rejected before any provider call;
- budget-exhausted plans are marked `SKIPPED_BUDGET` and do not invoke the callable;
- provider exceptions do not trigger implicit retries and do not expose exception text in receipts.

The unit of accounting is **one invocation of the injected callable**. If a provider adapter internally retries, fans out to multiple APIs, or invokes nested tools, those internal calls must be instrumented by that adapter; the outer receipt alone cannot establish their count. A returned sequence and its length are provider response data, not proof of relevance, freshness, or authoritative source verification.

This is a newly authored execution boundary, not evidence of live Search Agent activation. `search_stage.py` connects the plan and discovery stages when a caller explicitly injects a planner and provider callable, but the repository still configures neither by default. The tests for this stage adapter are authored but unexecuted.

## Search stage adapter behavior

- The planner is injected and may return Search Matrix combinations directly or legacy-style plan objects with a nested `combination` attribute.
- The plan handler rejects empty plans, malformed combinations, duplicate IDs, and plans exceeding the configured maximum; it does not silently truncate.
- The discovery handler requires a run ID, provider ID, callable, and positive call budget. Provider responses must be sequences of normalized `SearchProviderHit` values.
- Each result records provider ID, stable combination ID, provider result ID, title, source URL, observation time, SHA-256 of the query, and a run-scoped result reference.
- Each invocation receipt records start/end time, attempted status, result count, and outcome. When a budget leaves planned queries unexecuted or a provider call fails, discovery returns a non-success status and the pipeline stops rather than treating partial coverage as complete.
- A valid HTTP(S) URL is only a discovered URL. It does not establish official-source authority, currentness, or recruitment validity; later verification stages must establish those independently.

The adapter factory is available for application composition, but no concrete provider or legacy planner is selected by default. This keeps provider authorization and live credentials under caller control.

## Receipt contract

Each handler returns `StageExecution` with:

- an explicit `StageStatus`;
- a mapping of typed output values;
- optional output references;
- non-empty evidence references for stages declared `evidence_required`;
- a reason for FAILED, BLOCKED, or NOT_APPLICABLE outcomes.

The runner validates receipt shapes and stage prerequisites. A non-empty reference is only a pointer: it does not itself prove that the source is authoritative, current, authentic, or relevant. The adapter must make the verification result explicit in typed outputs and evidence metadata.

## Provider authorization and security

- Do not infer that a provider is authorized because its endpoint is reachable.
- Do not use candidate personal details in a query unless the data is necessary and the source/use is approved.
- Do not scrape behind authentication, CAPTCHA, anti-bot controls or access restrictions.
- Do not send raw candidate files or sensitive evidence to GitHub.
- Do not treat search simulation, cached results, provider metadata, or a URL's presence as a live retrieval receipt.
- Do not add live Notion writes until canonical identity, permissions, field minimization, retention, deletion, pagination, idempotency, conflict handling and read-back reconciliation are approved.
- Do not perform application submission, email dispatch or external mutation from this analysis workflow.

## Integration acceptance gate

Before any live adapter is enabled:

1. Record provider, access basis, allowed data, rate limits and operational owner.
2. Add deterministic fake-adapter tests for success, empty result, malformed response, permission denial, rate limit, timeout, stale result and partial failure.
3. Verify each receipt has source identity, observation time and traceable evidence refs.
4. Run the full synthetic workflow through `run_analysis` and retain the actual command/output.
5. Run controlled integration tests with credentials and candidate data excluded from logs.
6. Reconcile persisted state by read-back before claiming external writes succeeded.
7. Record uncovered paths and residual risks in `docs/delivery-evidence-ledger.md`.

Until those conditions are met, the application entry point is an injectable contract runner, not a production-connected recruitment service.
