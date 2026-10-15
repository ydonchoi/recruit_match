# Legacy Architecture Inventory and Disposition

- Status: **TRACKED-TREE INVENTORY COMPLETE / CALL-GRAPH TRACE PARTIAL**
- Source repository: [ydonchoi/recruitment_matching](https://github.com/ydonchoi/recruitment_matching)
- Source revision: `89899ee3b0719d73f36311004ac32f87e8a78dee`
- Inventory date: 2026-10-15
- Source instruction: [v5.4.25](https://github.com/ydonchoi/recruitment_matching/blob/main/docs/project-instruction-v5.4.25.md)

## Evidence and limits

The Git tree API returned `truncated=false` and 1,059 tracked paths at the source revision above. This establishes a complete tracked-path inventory for that revision, not complete content review or a complete call graph. Selected source files and policy documents were fetched and inspected; every file's contents were not read.

Counts are by top-level path and include directories as tree entries where applicable; they are inventory counts, not feature-completeness scores.

| Top-level area | Tracked paths | Classification / disposition |
|---|---:|---|
| `docs/` | 351 | Policy, architecture, schemas, specifications, audit and historical records. Preserve useful active contracts; do not port historical reports wholesale. |
| `registry/` | 257 | Domain records, schemas, evidence/provenance, assessments, compensation data, Python domain/persistence/writer code. Split executable domain from candidate-linked records; do not copy the latter to the new repo. |
| `tests/` | 169 | Python runners, test specifications, fixtures and historical validation records. Rebuild a compact test suite around behavior and evidence; fixtures must be synthetic. |
| `analysis/` | 134 | Search/ranking iterations, candidate-linked reports and validation records. Treat as historical artifacts; do not migrate candidate-specific outputs to GitHub. |
| `opportunities/` | 31 | Opportunity-specific records and active/closed/archived groupings. Preserve the logical opportunity lifecycle, not repository-file persistence. |
| `collection/` | 30 | Collection batches and evidence notes. Preserve acquisition lineage contracts; avoid copying run outputs and personal data. |
| `search_agent/` | 28 | Search routing, matrix, simulation, acquisition boundary, runtime, result assessment, feedback and adaptive planning. Port concepts selectively after caller and adapter contracts are resolved. |
| `candidate/` | 15 | Candidate profile, preferences, capability summaries and evidence index. Do not copy these files or their contents into the new repository. |
| `execution/` | 11 | Execution/evidence utilities. Preserve bounded, non-submission analysis behavior; no automatic application or email action. |
| `.github/` | 9 | CI workflows. Rebuild CI around the new contract and available execution environment; old workflow definitions do not prove tests pass. |
| `changelog/` | 9 | Historical changes and experiment records. Use as context, not as active policy unless explicitly referenced. |
| `crawl/` | 8 | Attachment policy, safe fetch and artifact storage. Preserve safe public-only retrieval concept; harden implementation and tests before enabling. |
| `tools/` | 3 | Utility scripts and safety check. Review against current active policy; the inspected safety check references an older instruction version. |
| `scripts/` | 2 | Supporting scripts; inspect individual callers before migration. |

Total tracked paths: **1,059**. File extension inventory: 831 Markdown, 162 Python, 7 YAML, 4 CSV, 1 JSON, 1 GitHub-specific file, 1 gitignore, plus 52 paths without a file extension and directory/tree entries as represented by the Git API inventory. Do not interpret extension counts as mutually exhaustive file-only counts because the tree response also includes directory entries.

## Architecture layers and decisions

| Layer | Legacy evidence | Target disposition | Reason / gate |
|---|---|---|---|
| Candidate Ground Truth and preferences | `candidate/`, `registry/candidate_vault.py`, `search_agent/search_matrix.py` | **RETAIN CONCEPT / REBUILD PRIVATE ACCESS** | Candidate facts are matching inputs, but the inspected vault is in-memory and repository files are not an acceptable private data store. No candidate records migrate to GitHub. |
| Search intent and routing | `search_agent/router.py`, `request_handler.py`, `chatgpt_binding.py` | **REBUILD / ADAPTER-DEPENDENT** | Top-level keyword routing and tool-call contracts exist, but concrete production search adapter connectivity is not established by these classes alone. |
| Search matrix and randomized simulation | `search_matrix.py`, `search_simulation.py`, `adaptive_planner.py` | **RETAIN CONCEPT / VERIFY** | Search axes, seeded probes and exploration/feedback separation are valuable; simulation must never be represented as actual source acquisition. |
| Multi-source discovery | `search_agent/orchestrator.py`, `runtime.py`, `source_acquisition.py`, platform registry | **REBUILD ADAPTER BOUNDARY** | The orchestrator receives an injected search executor. Source metadata presence does not establish authority or access authorization. |
| Opportunity resolution / deduplication | `registry/decision.py`, `enrollment.py`, resolver paths and schemas | **RETAIN CONCEPT / REBUILD** | Stable identity, duplicates, lifecycle and recruitment-cycle separation are needed; uniqueness and conflict behavior require explicit contracts. |
| Currentness / official verification | `search_policy.py`, source and writer gates | **RETAIN / FAIL CLOSED** | Keep currentness and authority as explicit evidence-backed states; missing evidence remains UNKNOWN. |
| Attachment crawl / inspection | `crawl/`, `docs/attachment-crawl-*` | **REBUILD AFTER SAFETY TESTS** | Policy-first public fetch is the right boundary, but the current fetch loop can silently stop at the byte limit and the robots read lacks an explicit timeout. Actual response MIME/magic-byte checks also need a tested boundary. |
| Recruitment evidence and provenance | `registry/06_Evidence/`, `registry/provenance/`, schemas | **RETAIN CONCEPT / MINIMIZE** | Separate candidate evidence from recruitment evidence; keep provenance pointers and decision-relevant extracts, not sensitive originals. Do not copy old records into the new repo. |
| Eligibility and fit | `registry/domain_adapters.py`, assessment schemas and ranking | **REBUILD AS EXPLICIT DOMAIN SERVICES** | Eligibility hard gates and fit dimensions must be independently represented; default numeric zeros must not stand in for missing assessment. |
| Compensation resolution | `registry/compensation_resolution.py`, compensation tables | **RETAIN PRIORITY ORDER / VERIFY SOURCES** | Official → institutional table → public benchmark → labeled estimate → UNKNOWN; preserve confidence, currency/period and provenance. Do not port old candidate-linked rows. |
| Ranking / Top-50 | `search_agent/ranking_policy.py`, `top50.py` | **RETAIN CONCEPT / REVALIDATE** | Preserve hard-gate-before-ranking and no-padding behavior; score remains a heuristic, not fact. |
| Registry Writer gate | `writer_contract.py`, `writer_gate.py`, `writer_runtime.py`, orchestrator | **SPLIT DECISION FROM MUTATION** | The gate can be useful without GitHub sync. The inspected orchestrator sets `approval_required=False`; do not port implicit mutation without explicit authorization contract. |
| GitHub Registry CRUD / sync | README pipeline and sync-related Notion fields | **RETIRE FROM DEFAULT TARGET** | Creates a second candidate/opportunity data copy and consistency burden. Legacy fields do not prove sync is needed. |
| Notion persistence | `registry/notion_registry.py` and observed Notion schema | **BLOCKED PENDING DATA/ACCESS REVIEW** | Schema is plausible but access controls, retention, field necessity and full identity relations are unverified; old adapter mapping is incomplete and has unsafe defaults. |
| Recall, revalidation, lifecycle and outcome feedback | `registry/recall.py`, `revalidation.py`, `search_agent/feedback.py`, `search_memory.py` | **RETAIN CONCEPT / REBUILD PERSISTENCE** | Separate lifecycle, readiness, outcome and feedback. Current memory stores are process-local, not durable stores. |
| CI / verification | `.github/workflows/`, 169 test/spec paths | **REBUILD / EXECUTE** | Existing instruction reports five workflow failures. Test files and historical reports do not prove the current code passes. |

## Cross-cutting runtime findings

1. **Success-shaped defaults:** inspected `registry/flow.py` constructs analysis rows with `duplicate_free=True`, `privacy_ok=True`, `schema_ok=True`, and score `0.0` when projection data is missing. These are unsafe defaults because absence is not verification and zero is a valid score. The replacement must represent UNKNOWN/unverified and missing score explicitly.
2. **Stage completeness:** `registry/pipeline_stages.py` can return `SKIPPED` when `allow_unconfigured=True`; the active instruction disallows `SKIPPED`, `ASSUMED_COMPLETE`, `IMPLICIT_PASS` and `UNCHECKED` for mandatory stages. The generic pipeline also records a context-returning stage as `completed: true` without a typed terminal outcome. This is a contract mismatch to fix before runtime use.
3. **Injected execution boundaries:** `search_agent/orchestrator.py` accepts a `search_executor`; the inspected source does not establish that a live search adapter is wired in production.
4. **Volatile state:** `MemoryStore` and `SearchMemory` use in-process dictionaries/lists. Restart recovery, multi-process consistency and durable idempotency are not established.
5. **Writer mutation:** a result can be externally mutated before its local result is stored; the failure/reconciliation window and concurrency behavior are unproven.
6. **Attachment byte limit:** `crawl/fetch.py` reads at most the remaining configured byte budget. When the budget is exhausted, it calls `read(0)` and may return a truncated artifact as if it were complete, instead of detecting an over-limit body. The robots.txt fetch has no explicit timeout in the inspected implementation. These are code-review findings, not runtime reproductions.
8. **Policy-version drift:** `tools/recruitment_safety_check.py` references v5.4.20 while the active instruction is v5.4.25; text-presence checks are not semantic or runtime safety proofs.
9. **Notion mapping gap:** the legacy adapter maps only a subset of the observed opportunity schema and has known first-match, pagination and success-default hazards. Do not port it wholesale.

## New-repository implementation started

- `src/recruit_match/pipeline.py` now defines a typed stage receipt, explicit bounded-run contract, predecessor list, and fail-closed validator. It rejects missing required receipts, duplicate receipts, unapproved NOT_APPLICABLE, FAILED/BLOCKED stages, predecessor mismatches, run ID mismatches and out-of-scope receipts.
- `src/recruit_match/runner.py` executes injected handlers in order, passes context in memory, stops on failures/blocks, and sanitizes handler exceptions. It does not provide durable persistence or production integrations.
- `src/recruit_match/attachments.py` defines an injectable URL/DNS/robots/transport boundary, manual redirect checks, size limits, basic PDF/ZIP signature and MIME checks, and a SHA-256 receipt. No production transport or live network behavior is included. The transport must pin the connection to validated public DNS addresses; this requirement is a contract, not yet an independently verified transport implementation.
- `docs/attachment-retrieval-boundary.md` records the remaining security work.
- `src/recruit_match/domain.py` now keeps lifecycle, currentness, source verification, eligibility, recommendation, execution readiness and application outcome separate. GitHub sync state has been removed from the domain record because GitHub registry sync is out of scope by default.
- Tests were added for these contracts, but have not been executed in this session. The validator is not yet wired into a runtime pipeline.

## Candidate-data boundary

The legacy tracked tree contains candidate-related paths, candidate-linked evidence/provenance records and ranking/analysis artifacts. The active instruction and its partial audit explicitly warn that a tree/content audit does not establish history, fork, cache, CI-artifact or external-copy erasure.

This inventory did **not** copy candidate records, personal details, ranking results, evidence bodies or application outcomes into the new repository. It did not delete or rewrite the legacy repository. Any cleanup of legacy data requires a separately scoped, field-by-field inventory and explicit history-remediation assessment; bulk deletion is not authorized by this inventory.

## Next implementation gates

1. Finalize a typed stage contract with explicit SUCCESS / FAILED / BLOCKED / permitted NOT_APPLICABLE outcomes and predecessor enforcement.
2. Make missing provenance, privacy review, schema validation, duplicate resolution, currentness and scores explicit UNKNOWN/unverified states.
3. Define adapter interfaces separately from domain logic; keep search, Notion, file retrieval and user decisions injectable and permission-gated.
4. Resolve private canonical persistence, field minimization, access control, retention and deletion semantics before implementing writes.
5. Harden attachment fetch (timeouts, response size detection, MIME/magic bytes, redirect/IP policy) and test negative/adversarial cases.
6. Separate recommendation from Registry persistence and from application execution.
7. Use synthetic-only fixtures, run tests in an environment with execution available, and attach real outputs before promoting the PR.

## Verification statement

- Tracked path inventory: **verified for source tree SHA `89899ee3b0719d73f36311004ac32f87e8a78dee`** (`truncated=false`, 1,059 paths).
- Selected code findings: **source-observed** from files named above; not all paths were reviewed.
- Test execution: **not performed** in this session. The unit-test workflow is authored but has no observed run.
- Full call graph, live search connectivity, live Notion writes, access control, data erasure, and production readiness: **unverified**.
