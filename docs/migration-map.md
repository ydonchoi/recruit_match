# Legacy Architecture Inventory and Migration Map

- Status: **PHASE 1 / PARTIAL INVENTORY — NOT A COMPLETE AUDIT**
- Target: `ydonchoi/recruit_match`
- Source: [`ydonchoi/recruitment_matching`](https://github.com/ydonchoi/recruitment_matching)
- Source active instruction reviewed: [v5.4.25](https://github.com/ydonchoi/recruitment_matching/blob/main/docs/project-instruction-v5.4.25.md)
- Source README reviewed: [README.md](https://github.com/ydonchoi/recruitment_matching/blob/main/README.md)
- Source architecture reviewed: [docs/architecture.md](https://github.com/ydonchoi/recruitment_matching/blob/main/docs/architecture.md)
- Audit date: 2026-10-15

## Purpose

The goal is to review and account for the **whole legacy architecture**, then selectively migrate, redesign, rebuild, or retire each part. This is not a decision to migrate only the data model. Nor is it a blind copy of the old implementation.

This inventory is partial because not every module, test, workflow, fixture, and document has yet been inspected. No row below should be interpreted as a complete implementation or regression audit.

## Evidence and status vocabulary

- **SOURCE-DOCUMENTED**: described by a reviewed source document.
- **CODE-OBSERVED**: supported by the specific source code inspected.
- **TEST-EVIDENCE-UNKNOWN**: relevant test outcome has not been independently retrieved or executed here.
- **PROPOSED**: a target design decision for the new implementation, not an existing capability.
- **UNASSESSED**: source coverage is insufficient to decide migration disposition.

## Architecture inventory and provisional disposition

| Area | Legacy responsibility / documented flow | Initial disposition | Known questions / risks |
|---|---|---|---|
| Access governance | Public/authorized access boundary; no auth, CAPTCHA, anti-bot, or access-control bypass | **KEEP / REVALIDATE** | Map every collector and attachment fetch path to the policy and negative tests |
| Candidate Ground Truth and privacy | Separate candidate facts from inference and recruitment evidence; minimize retained personal data | **KEEP / REVALIDATE** | Audit models, logs, fixtures, reports, caches, Git history and access paths; do not migrate sensitive originals |
| Search axes and intent routing | Candidate ground truth -> search matrix -> top-level recruitment intent routing | **REVIEW / SELECTIVE MIGRATION** | Identify actual entry points, bounded-run profiles, tool-call contracts, and fallback behavior |
| Search simulation and adaptive loop | Seeded randomized repeated search; Search -> observed utility -> metric engine -> adaptive update -> independent validator | **REVIEW / SELECTIVE MIGRATION** | Distinguish simulation from live source acquisition; verify independent validator is not merely reusing metric-engine decisions |
| Source acquisition and coverage | Multi-source discovery across requested channels | **REVIEW / REBUILD BOUNDARIES IF NEEDED** | Establish source coverage evidence, rate limits, retries, source-level provenance, and tool access status |
| Opportunity resolution and identity | Discovery, duplicate/currentness checks, opportunity/posting identity | **REVIEW / REDESIGN CONTRACTS** | Define stable identity keys, duplicate policy, canonical source, pagination, and conflict handling |
| Recruitment cycle / currentness | Time-bound JD, requirements, compensation, employment conditions and assessment | **KEEP INVARIANT / REIMPLEMENT AS NEEDED** | Prevent historical-cycle facts and assessments from being silently reused as current |
| Attachment acquisition and inspection | Discovery -> policy gate -> safe fetch -> hash -> extraction -> atomization -> evidence consolidation -> reassessment | **KEEP SAFETY CONTRACT / AUDIT IMPLEMENTATION** | Each stage must have an explicit terminal outcome; no attachment content inferred from links alone |
| Requirement and functional model | Position -> functional composition -> recruitment cycle -> requirement -> evidence mapping -> assessment | **KEEP CONCEPT / REVIEW IMPLEMENTATION** | Ensure requirement-level evidence relations and critical-gap propagation are explicit |
| Evidence and provenance | Separate Candidate Evidence from Recruitment Evidence; preserve source and lineage | **KEEP / STRENGTHEN CONTRACT** | Confirm evidence records preserve origin, time, hash/reference, verification, and uncertainty without copying sensitive originals |
| Eligibility, fit, compensation | Critical eligibility gate, fit, gap/unknown, official-to-estimate compensation resolution | **KEEP DECISION INVARIANTS / REVALIDATE LOGIC** | Unknown must not be treated as pass, fail, zero, or below-minimum; test hard-gate precedence |
| Top-50 analytical board | User-facing ranked shortlist | **REVIEW / SELECTIVE MIGRATION** | Ranking output must remain distinct from recommendation, Registry write eligibility, and human decision |
| Recommendation and revalidation | Recommendation -> revalidation -> reassessment/revision | **KEEP BOUNDARY / REBUILD STATE CONTRACTS AS NEEDED** | Define material-change triggers, freshness windows, and explicit invalidation/reassessment transitions |
| Registry enrollment and lifecycle | Logical registry, durable-store hydration, lifecycle/revalidation, recall | **REDESIGN STATE MODEL** | Inspected code writes both execution readiness and application outcome into `execution_state`; state semantics are conflated |
| Registry Writer and approval | Contract assessment -> approval gate -> external mutation -> result persistence | **REDESIGN / TEST FAILURE WINDOWS** | Inspected runtime writes external mutation before result-store persistence; duplicate execution risk exists if acknowledgement fails or calls race |
| Notion adapter and durable projection | Translate domain records to Notion properties; create/update/query/upsert | **REBUILD ADAPTER CONTRACT** | Inspected upsert queries only one page of up to 10 matches and updates the first match; missing state fields default to success-shaped values; projection hardcodes `duplicate_free`, `privacy_ok`, and `schema_ok` true |
| GitHub Registry Sync / batch integration | Collection branch -> batch validation -> PR -> review/merge -> main validation; Registry write and sync are separate | **REVIEW / REBUILD END-TO-END WIRING** | Current actual trigger-to-writer-to-sync call path has not been proven end-to-end |
| Execution readiness / human decision / application | Execution readiness, priority, human decision, application strategy/execution, outcome, new evidence | **KEEP HUMAN BOUNDARY / REBUILD STATE MODEL** | No automatic application submission or email sending is allowed by the legacy README; preserve this boundary unless explicitly changed |
| Quality metrics and feedback | Baseline -> observation -> hypothesis -> minimal change -> test -> result -> review | **KEEP / MAKE EVIDENCE-BACKED** | Do not invent baselines or targets; report unmeasured values as unverified |
| Tests and CI | Multiple workflow suites for pipeline, registry, writer, execution, safety and contracts | **INVENTORY REQUIRED** | Active instruction records five workflow failures in PR #153; current test coverage and outcomes must be retrieved/run before migration decisions |
| Documentation / artifact hygiene | Active instruction, architecture, design proposals, experiments, historical reports, artifact register | **AUDIT BEFORE MOVE/DELETE** | Source artifact register says inventory review and exhaustive link validation remain pending; file count alone is not semantic classification |

## Source-backed findings from inspected code

1. `registry/enrollment.py`: `set_execution_readiness()` and `record_application_outcome()` both write into `execution_state`. This is a code-observed state-model collision.
2. `registry/writer_runtime.py`: the external mutation happens before the result is stored. A crash or result-store failure after mutation, or concurrent execution, can undermine effective idempotency unless the adapter/store supplies additional guarantees.
3. `registry/notion_registry.py`: `search_by_opportunity_id()` requests `page_size: 10` without pagination; `upsert()` creates when no match exists or updates the first match. It does not resolve multiple matches.
4. `registry/notion_registry.py`: missing Promotion State and Lifecycle State values are defaulted to `PROMOTED` and `ACTIVE`; the analysis projection hardcodes duplicate/privacy/schema flags to true and derives source verification from string presence.
5. Legacy README and architecture documentation describe many stages and invariants, but documentation is not proof that every stage is wired into a live end-to-end runtime.

These are scoped findings from the files inspected, not a complete repository audit.

## New implementation bootstrap: status

The current `src/recruit_match/domain.py` model is **PROVISIONAL**. It is a small testable starting point, not the canonical model and not evidence that the complete legacy architecture has been migrated.

Do not expand it into the full domain model until the inventory, contracts, and target architecture have been reviewed.

## Next audit steps

1. Enumerate the source repository's tracked paths and identify actual runtime entry points.
2. Build a module map: imports/dependencies, callers/callees, side effects, persistence, event triggers, and test links.
3. Retrieve relevant test files and historical/current CI outcomes; distinguish executable tests from narrative plans.
4. Trace each documented pipeline stage to implementation, test evidence, and runtime trigger.
5. Produce a migration matrix with one decision per module: **KEEP**, **REFACTOR**, **REBUILD**, **RETIRE**, or **UNASSESSED**, each with evidence and rationale.
6. Finalize target architecture and data model only after material conflicts and unknowns are recorded.
7. Keep the new repository's bootstrap PR as a draft until the architecture review and migration plan are accepted.

## Non-claims

This document does not claim:
- that the legacy architecture has been exhaustively inspected;
- that any unrun tests pass;
- that Notion or GitHub sync works end-to-end;
- that the proposed target architecture is implemented;
- that a local test pass certifies production readiness.


## Target migration decision added 2026-10-15

- GitHub Registry create/update/delete and registry-sync are **OUT OF SCOPE by default** for the new repository. Do not reproduce the legacy GitHub Sync stage merely because the old README includes it.
- Notion persistence is **UNASSESSED / BLOCKED pending schema and access review**. No live Notion adapter or write path is to be implemented until the actual DB model, access controls, retention, minimum fields and required workflows have been reviewed.
- Preserve the logical Registry concept only if the end-to-end pipeline requires a durable opportunity lifecycle. Do not assume a particular backend before the schema review.
- Candidate-specific records, personal data, assessment outputs and sensitive source material are not permitted in GitHub. Any legacy cleanup is a separate, scoped task; no historical deletion is claimed.
- The data-boundary decision is recorded in [data-boundary-decision.md](data-boundary-decision.md), the partial runtime trace in [pipeline-execution-trace.md](pipeline-execution-trace.md), and the current target-side static review in [static-review-and-migration-status.md](static-review-and-migration-status.md).


## Additional source-code observations added 2026-10-15

- `search_agent/source_acquisition.py` checks that source ID, URL, type, acquisition time and content identity are present. This is a provenance completeness check, not source-authority or access-policy verification.
- `search_agent/platform_registry.py` initializes nine platform descriptors as enabled while `policy_status` defaults to `REVIEW_REQUIRED`. A rebuilt system must gate actual adapter use on authorization and policy state, not descriptor enablement alone.
- `registry/candidate_vault.py` is an in-memory versioned Candidate Ground Truth store with approval-reference and authorization-verifier checks. The inspected implementation is not a durable secure storage solution; do not port real candidate payloads into the GitHub repository.
- `search_agent/independent_validator.py` defines ACCEPT, REJECT, INCONCLUSIVE and ROLLBACK_REQUIRED. The independent nature of its utility signal still needs caller-level tracing and test evidence.
- The source candidate-data audit dated 2026-10-10 is itself explicitly partial and leaves Git history, artifacts, caches, forks, external storage and repository access exposure unresolved. It recommends field-by-field minimization rather than bulk deletion.


## Notion schema review result added 2026-10-15

Schema metadata was inspected from the connected Notion workspace (no data rows queried). The canonical opportunity registry includes lifecycle/eligibility/recommendation/execution/revalidation fields and also `GitHub Source` / `Notion Sync State`. Separate Candidate Profile and Candidate Evidence data sources include candidate-linked fields such as name, preferences, compensation, capability, achievement and evidence. Data-source separation does not establish separate access permissions.

**Disposition remains:** no GitHub registry CRUD/sync; Notion writes blocked until access, retention, field necessity and workflow review. The presence of legacy sync-related properties is not sufficient evidence to implement a GitHub mirror.
