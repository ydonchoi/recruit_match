# Static Review and Migration Status

- Review date: 2026-10-15
- Target repository: `ydonchoi/recruit_match`
- Branch: `bootstrap/verification-first-architecture`
- Review mode: source inspection only; **no test, import, network, or end-to-end execution was performed**
- Related evidence: [delivery evidence ledger](delivery-evidence-ledger.md), [legacy inventory](legacy-architecture-inventory.md), [pipeline trace](pipeline-execution-trace.md)

## Status vocabulary

- **IMPLEMENTED-SOURCE-REVIEWED**: code exists and its source was inspected; runtime behavior is not established.
- **CONTRACT-ONLY**: interface and failure policy exist, but no real provider/adapter is connected.
- **PARTIAL**: some modules or paths were inspected; the end-to-end legacy path is not yet proven.
- **BLOCKED**: intentionally not enabled until policy, access, or data-boundary prerequisites are resolved.
- **UNVERIFIED**: evidence is insufficient to claim behavior or completion.

## Static-review changes made in this pass

| Area | Finding | Change | Evidence status |
|---|---|---|---|
| Currentness vocabulary | Recommendation logic recognized `CLOSING_SOON` and `EXPIRED`, but the canonical enum did not declare them | Added both states to `CurrentnessState`; recommendation input and handler now require that enum instead of arbitrary strings | Source reviewed; tests authored, not run |
| Requirement identity | Duplicate requirement IDs could make the evidence/decision mapping ambiguous | Eligibility evaluation now rejects duplicate IDs and malformed input collections | Source reviewed; tests authored, not run |
| Eligibility evidence | The previous gate required both evidence domains and a non-empty refs tuple, but did not require two distinct references | Critical decisions now require both domains and at least two distinct refs; duplicate domain labels do not satisfy the gate | Source reviewed; tests authored, not run |
| Ranking identity | Duplicate opportunity IDs could be silently ranked as separate candidates | Ranking now rejects duplicate IDs | Source reviewed; tests authored, not run |
| Attachment policy | Python truthiness meant a non-boolean value such as the string `"false"` could pass the affirmative policy gate | Policy decision and robots flag must be actual booleans; allowlist and user-agent shapes are validated | Source reviewed; tests authored, not run |
| DNS resolver boundary | Malformed resolver address tuples could raise an unclassified exception | Resolver results are shape-validated and malformed responses fail with a sanitized policy error | Source reviewed; tests authored, not run |

These are code changes, not verified fixes. No runtime result is claimed.

## Target architecture migration status

| Legacy area / responsibility | Target status | Evidence and remaining work |
|---|---|---|
| Candidate Ground Truth / privacy boundary | **CONTRACT-ONLY / BLOCKED** | No candidate-specific data copied. Approved private source, minimum fields, access, retention, deletion and redaction policy remain unresolved. |
| Search axes, intent routing, randomized simulation and adaptive loop | **PARTIAL** | Legacy docs and selected files inspected. No live search planner/provider, adaptive loop, or independent utility-validator integration is wired into the target. Simulation must never count as source retrieval. |
| Multi-source acquisition and source coverage | **CONTRACT-ONLY** | Discovery adapter contract exists; no authorized live source adapters or retrieval receipts configured. |
| Opportunity identity, recruitment cycle and duplicate resolution | **PARTIAL / CONTRACT-ONLY** | IDs and duplicate-state contracts exist. Canonical identity keys, cycle matching, conflict policy, and real source-level resolution are not implemented. |
| Official source verification and currentness | **CONTRACT-ONLY** | Typed states and recommendation gates exist; no independent official-source verification adapter is configured. |
| Attachment policy and public HTTPS fetch | **IMPLEMENTED-SOURCE-REVIEWED, UNVERIFIED** | Allowlist, DNS public-address checks, numeric-IP connection, TLS hostname verification, redirect policy, robots gate, time/size bounds, MIME/magic checks and integrity receipt exist in source. Network behavior is untested. |
| Attachment parsing / inspection / evidence atomization | **CONTRACT-ONLY / NOT IMPLEMENTED** | Fetcher only classifies PDF or ZIP-container signatures. It does not parse PDFs, inspect ZIP member paths, enforce expanded-size/entry-count limits, extract evidence, or establish semantic correctness. Do not describe fetching as inspection. |
| Candidate and recruitment evidence lineage | **CONTRACT-ONLY** | Requirement checks require separate evidence domains and refs, but refs are opaque pointers; authenticity, authority, time, content hash, and source-location semantics must be supplied and checked by future adapters. |
| Eligibility and fit | **IMPLEMENTED-SOURCE-REVIEWED** | Pure functions and handlers exist; runtime behavior and evidence-to-requirement matching remain unverified. |
| Compensation resolution | **IMPLEMENTED-SOURCE-REVIEWED** | Evidence tiers and estimate assumptions are represented. Currency, pay period, gross/net, employment fraction, date normalization, and range comparability are not normalized. |
| Ranking / Top-50 | **IMPLEMENTED-SOURCE-REVIEWED** | Hard eligibility FAIL is excluded, missing scores are not coerced to zero, and no padding occurs. Ranking semantics still need an explicit product decision on dimension precedence and UNKNOWN inclusion. |
| Recommendation / revalidation | **PARTIAL** | Recommendation is fail-closed on typed gates. Material-change triggers, freshness windows, invalidation transitions and repeated-run behavior are not implemented. |
| Registry, persistence, recall and lifecycle | **BLOCKED / NOT IMPLEMENTED** | No canonical private store, transaction boundary, durable event/receipt store, idempotency key, concurrency control or recovery protocol is selected. |
| Notion adapter | **BLOCKED** | No live reads/writes; schema and data-boundary review does not yet authorize an adapter. |
| GitHub Registry CRUD / sync | **OUT OF SCOPE BY DEFAULT** | Do not port the legacy writer/sync merely because it exists in the old architecture. No candidate-linked data or source documents should be stored in GitHub. |
| Human decision, application execution and outcome | **BOUNDARY PRESERVED / NOT IMPLEMENTED** | Analysis does not submit applications or send emails. Execution readiness, human approval, external action and application outcome remain distinct. |
| Observability, audit and feedback metrics | **PARTIAL / UNVERIFIED** | Receipts and an evidence ledger contract exist; there is no durable redacted telemetry, measured baseline, operational alerting, or quality feedback loop. |
| CI and tests | **TEST-AUTHORED / EXECUTION UNKNOWN** | 121 test functions are present by source inspection. No assertions have been executed and no passing count is known. |

## High-priority unresolved issues

1. **No end-to-end runtime path.** The 18-stage workflow is a contract runner. Missing external adapters stop the run; no live source, private candidate context, persistence or external write path is configured.
2. **Attachment fetch is not content inspection.** PDF/ZIP magic checks do not establish parse safety or semantic validity. ZIP decompression limits, parser isolation, malformed document handling, and content extraction need a separate sandboxed inspection boundary.
3. **Evidence refs are not evidence validation.** Non-empty references and domain labels cannot establish authority, authenticity, relevance, freshness, or a correct candidate-to-requirement match.
4. **No persistent idempotency/recovery design.** Run IDs and in-memory receipts do not protect against process restart, duplicate requests, concurrent writers, partial external mutation or lost acknowledgements.
5. **Assessment semantics need product-level decisions.** Ranking prioritizes eligibility, job fit, career/education fit, location, then total score; this precedence is encoded but not justified by a measured baseline. UNKNOWN candidates are retained for review, not promoted as PASS.
6. **Legacy caller tracing remains partial.** The 1,059 tracked-path inventory is not equivalent to a complete semantic audit. Each important entry point, caller/callee path, side effect, test and workflow still needs evidence.
7. **Test coverage is not test execution.** The added test cases have not been run. Syntax, import compatibility, actual socket/TLS behavior and full-workflow behavior remain unknown.

## Next static-only work

1. Complete a legacy entry-point and caller/callee matrix for each runtime subsystem and workflow.
2. Inspect test and workflow files associated with legacy registry writer, Notion adapter, source acquisition, independent validator, attachment fetching, and execution boundary.
3. Write explicit contract tests for duplicate/conflicting identities, stale revalidation, retry/replay, partial failures, and evidence lineage; keep them marked unexecuted.
4. Specify a sandboxed document-inspection contract before implementing PDF/ZIP parsing.
5. Specify compensation normalization and ranking policy before adding more scoring behavior.
6. Keep PR #1 Draft. Do not merge or enable live adapters until runtime evidence and data-boundary approvals exist.

## Non-claims

This review does not claim a complete legacy audit, passing tests, safe live network transport, production-ready attachment parsing, privacy compliance, functioning persistence, or production readiness.
