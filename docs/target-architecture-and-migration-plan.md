# Target Architecture and Migration Plan

- Status: **DESIGN PROPOSAL + PARTIAL CONTRACT IMPLEMENTATION — EXTERNAL INTEGRATION NOT IMPLEMENTED**
- Date: 2026-10-15
- Decision scope: rebuild `ydonchoi/recruit_match` from a clean repository without copying candidate records.

## Design principles

1. Domain contracts own meaning; adapters translate external formats; orchestration enforces stage order; CLI/UI/ChatGPT bindings are outer adapters.
2. Keep candidate ground truth separate from job-posting content, recruitment evidence, assessment, recommendation and user decision.
3. Missing, conflicting or stale evidence remains UNKNOWN/UNVERIFIED. No default TRUE, PASS, ACTIVE, PROMOTED or numeric zero for missing facts.
4. Every required stage emits an explicit terminal outcome, attempt, evidence/provenance and downstream transition decision. A later success cannot hide an earlier missing stage.
5. Search simulation is planning evidence only, not proof that a source was queried.
6. Registry decision eligibility is not external persistence; persistence is not application submission.
7. GitHub stores code, non-sensitive contracts, synthetic fixtures and sanitized verification output only.
8. Candidate records are not migrated into this repository. No live Notion writes before access and minimization review.

## Target component boundaries

```
Request / User Intent
  -> Run Contract and Scope
  -> Candidate Context Provider (approved private source; minimum fields)
  -> Search Planner (axes, deterministic/randomized probes, exploration)
  -> Authorized Search Adapters
  -> Acquisition Trace / Source Provenance
  -> Opportunity Identity Resolution + Duplicate Conflict Gate
  -> Official Source / Currentness Verification
  -> Attachment Policy Gate -> Safe Fetch -> Integrity -> Extraction
  -> Requirement Atomization -> Recruitment Evidence Graph
  -> Candidate Evidence Resolver (separate source and access boundary)
  -> Mandatory Eligibility Gate
  -> Fit / Preference / Location Assessment
  -> Compensation Resolution with source tier and confidence
  -> Ranking / Top-N projection (no padding)
  -> Recommendation Proposal (no mutation)
  -> Revalidation and explicit human decision
  -> Approved private persistence (not yet selected/authorized)
  -> Application readiness/outcome feedback (no automatic submission)
```

The sequence is a target contract. The current code now exposes `run_analysis(...)` through `src/recruit_match/application.py` and can execute a synthetic workflow when handlers are injected; no real external adapters or persistence are configured, and that synthetic test has not been executed.

## Stage envelope

Every stage should accept a typed input and return:

- `stage_id`, `run_id`, `contract_version`
- `status`: SUCCESS, FAILED, BLOCKED, or NOT_APPLICABLE only where the contract explicitly permits it
- `attempt`, `started_at`, `finished_at`
- input/output references and provenance references
- warnings, unknowns, failure/block reasons
- predecessor IDs and downstream eligibility decision

No mandatory stage may return `SKIPPED`, `ASSUMED_COMPLETE`, `IMPLICIT_PASS`, or `UNCHECKED`. Partial runs are allowed only when the run contract declares its bounded scope and completion condition.

See [adapter-contracts.md](adapter-contracts.md) for the explicit provider boundary and integration acceptance criteria. The public `run_analysis(...)` entry point exists, but live providers are not configured.

## Persistence boundary

- Candidate context and candidate evidence: approved private store only, minimum necessary fields.
- Opportunity/recruitment records: approved private store after schema and access review.
- Raw candidate documents: do not copy into GitHub; prefer independently controlled references.
- Job-posting attachments: transient processing by default; retain decision-relevant text/metadata only where necessary and authorized.
- GitHub: source code, sanitized architecture docs, synthetic tests and test evidence with no personal data.
- Notion: candidate canonical-store option, not yet approved for writes. The existing Notion schema is a starting point for review, not an implementation contract.
- GitHub registry CRUD/sync: retired from the default target.

## Recommended module plan

1. `domain/`: lifecycle, identity, evidence, eligibility, fit, compensation, recommendation, decision, outcome contracts.
2. `contracts/`: stage envelopes, source provenance, persistence interfaces and schema versions.
3. `application/`: pipeline orchestration, bounded-run enforcement, dependency checks, replay/revalidation coordination.
4. `adapters/search/`: policy-gated source adapters, rate limits, acquisition receipts; no credentials or private-source bypass.
5. `adapters/attachments/`: URL/redirect policy, bounded safe fetch, content sniffing, hash, extraction interface and user-assisted fallback.
6. `adapters/persistence/`: one approved private-store adapter only after schema/access approval; no GitHub candidate registry adapter.
7. `evaluation/`: synthetic fixtures, contract tests, adversarial tests, regression cases and benchmark harness.
8. `observability/`: redacted stage receipts and error classifications; no candidate text or source-document bodies in logs.
9. `interfaces/`: CLI/ChatGPT/UI surfaces that cannot bypass domain gates.

## Implementation order

- **Gate 0 — source inventory:** tracked-tree inventory completed for source SHA `89899ee3b0719d73f36311004ac32f87e8a78dee` (1,059 paths, not truncated); complete call graph and full file-content review remain open.
- **Gate 1 — contract and privacy boundaries:** documented. No real-data migration.
- **Gate 2 — initial contracts:** provisional opportunity state separation and typed stage receipt/run validator added; tests written but not executed, and the validator is not wired into a runtime.
- **Gate 2 — domain contracts:** strict enums, UNKNOWN semantics, identity/conflict and stage result types; synthetic-only tests.
- **Gate 3 — execution pipeline:** enforce predecessors and bounded-run contract; no external mutation.
- **Gate 4 — search and attachment adapters:** policy-first, explicit access and source authority, deterministic traces, adversarial tests.
- **Gate 5 — analysis:** evidence, eligibility, fit, compensation, ranking and recommendation, each independently testable.
- **Gate 6 — persistence decision:** review Notion permissions/schema/retention and candidate field necessity; then select a private store.
- **Gate 7 — persistence and lifecycle:** idempotency, concurrency, duplicate handling, reconciliation and deletion/retention tests.
- **Gate 8 — end-to-end verification:** execute tests, inspect logs, validate synthetic traces, and record gaps. No merge without actual evidence.

## Implementation status update (2026-10-15)

- Added an in-memory bounded runner (`src/recruit_match/runner.py`) over the stage contract. It invokes injected handlers sequentially and stops after an invalid/non-success stage. It does not itself connect live search, Notion or any external mutation.
- Added a policy-gated attachment boundary (`src/recruit_match/attachments.py`) with allowlist, DNS-pinned numeric socket connection, TLS hostname verification, redirect checks, robots, size, MIME/signature and receipt checks. Parser isolation and live adversarial network testing remain unimplemented; source implementation is not production verification.
- Added `pyproject.toml` and a GitHub Actions unit-test workflow. One hundred and two test functions are authored across eight files. No usable test output exists: the observed Actions run failed before exposing steps or logs. See [delivery-evidence-ledger.md](delivery-evidence-ledger.md).

## Explicit non-goals

- Copying the legacy repository tree or candidate-related Markdown/CSV/JSON.
- Implementing GitHub Registry CRUD or a GitHub sync stage.
- Live Notion writes during architecture discovery.
- Authentication/CAPTCHA/anti-bot/access-control bypass.
- Automatic application submission, email sending or unapproved external mutation.
- Claiming tests, runtime connectivity, data deletion or privacy compliance without evidence.

## Open decisions

- Which approved private data store is canonical after access and retention review?
- Which candidate fields are strictly necessary for the matching workflow?
- Does `07 Job Candidate Registry` represent a distinct entity, a legacy projection or a duplicate of the canonical opportunity registry?
- What is the allowed state vocabulary and transition graph for each text/select state?
- Which external search adapters are authorized and actually available in the execution environment?
- What retention period and deletion protocol applies to evidence references, extracted recruitment text and run receipts?
