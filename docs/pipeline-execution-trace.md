# Legacy Pipeline Execution Trace

- Status: **PHASE 1 / PARTIAL SOURCE TRACE**
- Source: [ydonchoi/recruitment_matching](https://github.com/ydonchoi/recruitment_matching)
- Active source instruction: [v5.4.25](https://github.com/ydonchoi/recruitment_matching/blob/main/docs/project-instruction-v5.4.25.md)
- Date: 2026-10-15

## Scope and confidence

This traces the documented pipeline and selected implementation files fetched from the source repository. It is not a complete call graph: not every module, import, entry point, or test has been inspected, and no live end-to-end execution was performed. Documented architecture is not proof of runtime wiring.

## Documented end-to-end pipeline

The source README declares:

`Candidate Ground Truth → Search Matrix → Randomized Simulation → Multi-Source Discovery → Currentness/Urgency → Official Verification → Attachment Inspection → Evidence → Eligibility → Fit → Compensation → Top-50 → Registry Writer → Recommendation → Revalidation → GitHub Sync`

The source architecture expands this into access governance; candidate ground truth; search axes and intent routing; batch collection; search-run/tool-call planning; source acquisition; opportunity resolution; official posting/currentness; attachment inspection; recruitment cycle/JD/requirements; candidate and recruitment evidence; provenance/assessment; recommendation and Registry Write Eligibility; Registry write/sync; execution readiness and human decision; application/outcome/reassessment.

## Selected implementation trace

| Component | Code observed | Remaining verification |
|---|---|---|
| Search policy (`search_agent/search_policy.py`) | Explicit source, location, fit, currentness and urgency priorities | Actual callers, policy enforcement and live source adapters |
| Search matrix (`search_agent/search_matrix.py`) | Candidate-evidence-driven search combinations, stable IDs, learned/search expansion axes | Determine exactly which candidate facts enter query generation, how those facts are minimized, and which orchestration paths invoke the planner |
| Search runtime (`search_agent/runtime.py`) | Calls `source_acquisition.acquire`, `resolver.resolve`, `assessor.assess`, stores run and emits traces; can persist search-axis learning | Default values `decision_source_verified=True`, `privacy_ok=True`, and `schema_ok=True` are success-shaped when upstream fields are absent; confirm caller contracts and remove unsafe defaults in any rebuilt path |
| Randomized simulation (`search_agent/search_simulation.py`) | Seeded shuffle, iterations, source rotation, deterministic probe IDs | Simulation is not evidence of actual external search; trace the adapter boundary |
| Top-50 (`search_agent/top50.py`) | Sorts by eligibility category, fit, preference fit, location priority and score; does not pad results | Input construction, score provenance, UNKNOWN behavior in all downstream paths |
| Compensation (`registry/compensation_resolution.py`) | Official → institution table → public benchmark → estimate → UNKNOWN; estimate confidence LOW | Source validation, time/currency normalization, assumptions and threshold logic |
| Writer gate (`registry/writer_gate.py`) | Checks identity/cycle, authoritative source, active lifecycle, deadline, critical requirements, evidence separation, provenance and duplicate-free flag | Whether booleans are evidence-derived or caller-supplied; gate enforcement in full runtime |
| Enrollment (`registry/enrollment.py`) | In-memory projection, optional durable store, recall and revalidation methods | Durable transactions and concurrency semantics |
| Writer runtime (`registry/writer_runtime.py`) | Assess → approval when needed → external mutation → local result-store write | Mutation-before-acknowledgement creates a failure window; concurrency/replay safety unproven |
| Notion adapter (`registry/notion_registry.py`) | Maps records to Notion properties; query, upsert, hydration and analysis projection | One query is capped at 10; upsert updates first match; missing states default to success-shaped values; some quality flags are hardcoded true |
| Attachment fetch (`crawl/fetch.py`, `crawl/binary_fetcher.py`) | Two separate fetch implementations exist, with different policy/redirect/size behavior | `fetch.py` may return truncated bytes at the cap and does not explicitly reject same-host HTTPS→HTTP redirects; robots retrieval lacks an explicit timeout. `binary_fetcher.py` checks final URL only after following redirects and treats an empty allowlist as no host restriction; its purported empty-allowlist test uses a non-empty allowlist. These are source-review findings, not runtime reproductions |
| Safety gate (`tools/recruitment_safety_check.py`) | Static text-presence check only; no network or shell execution | It references v5.4.20 while v5.4.25 is active; text presence is not semantic/runtime safety |
| Notion adapter tests (`tests/test_notion_registry.py`) | Fake-transport tests cover create, update, projection, and hydration behavior | Existing tests encode create/update persistence expectations but do not establish privacy approval, schema suitability, real API correctness, pagination edge cases, or safe concurrency |
| CI workflows | Syntax, contract, safety, registry, search and execution test commands are defined | Active instruction reports five workflow failures in PR #153; current run results and full logs not verified here |

## Invariants to preserve

- Search axis ≠ score bonus; discovery ≠ recommendation.
- Candidate Evidence ≠ Recruitment Evidence; evidence ≠ assessment.
- UNKNOWN ≠ PASS/FAIL/zero.
- Critical eligibility failure cannot be offset by fit.
- Compensation estimate ≠ official compensation.
- Top-50 ≠ Registry Writer recommendation; recommendation ≠ human decision.
- Registry promotion ≠ GitHub commit; PR merge ≠ application execution.
- Attachment discovery, fetch, extraction, atomization and evidence consolidation are separate states.
- Bounded runs cannot be represented as completed full runs.

## Runtime boundary findings

The inspected `search_agent/runtime.py` constructs an `Opportunity` with `decision_source_verified=True`, `privacy_ok=True`, and `schema_ok=True` as defaults when upstream objects omit those fields. This can turn missing evidence into success-shaped values at that boundary. A replacement runtime must preserve explicit UNKNOWN/unverified states and derive privacy/schema verification from actual checks, not defaults. This is a code-observed risk, not proof that every upstream path currently omits those fields.

## Registry mutation boundary finding

The inspected `search_agent/orchestrator.py` invokes an injected `registry_writer.execute(proposal)`, and the proposal is constructed with `approval_required=False`. When the result is `READY_TO_MUTATE`, the orchestrator enrolls the opportunity into `UserRegistry`; that registry defaults to in-memory storage unless a store supplies one. The writer runtime can separately invoke an injected mutation adapter. This means the Registry Writer is not proven to be synonymous with GitHub sync: its eligibility/decision function may still be useful even if GitHub CRUD/sync is removed. Before rebuilding it, separate (a) recommendation/eligibility, (b) private-store persistence, and (c) any optional external mutation. Do not port an implicit auto-mutation path without a clear authorization contract.

## Notion schema evidence

The connected Notion workspace exposes a canonical opportunity data source with lifecycle, eligibility, score, recommendation, execution, revalidation and provenance fields, including `GitHub Source` and `Notion Sync State`. It also exposes separate Candidate Profile and Candidate Evidence data sources containing candidate-linked fields such as name, preferences, compensation, capability, achievement, evidence and source. This confirms a data-source-level separation, not separate access permissions. The field names `GitHub Source` and `Notion Sync State` do not prove GitHub sync is necessary or operational. Schema metadata was inspected; no candidate rows were queried.

## Persistence decision

The legacy pipeline documents GitHub Sync and collection-branch/PR integration. These are legacy concepts, not automatic requirements for the new repository. The new target does **not** implement GitHub registry CRUD or candidate/opportunity registry sync by default. GitHub is reserved for source code, non-sensitive policies, synthetic tests and sanitized technical documentation. See [data-boundary-decision.md](data-boundary-decision.md).

## Next trace work

1. Enumerate the complete tracked tree and classify runtime, contract, test, design, experiment and historical artifacts.
2. Follow imports/callers from top-level intent routing through acquisition and analysis.
3. Trace candidate facts and evidence references through each stage and minimize persisted fields.
4. Trace writer callers and determine whether Registry Writer has any independent purpose once GitHub sync is removed.
5. Retrieve current workflow outcomes and run tests in a permitted environment; never infer success from workflow definitions.
6. Compare the actual Notion schema against the minimum data model for recall, reassessment and application tracking.
7. Update this trace with exact code and test evidence as paths are verified.

## Non-claims

This trace does not establish complete runtime connectivity, passing tests, live Notion correctness, production readiness or exhaustive source coverage.


## Additional caller-level trace (source revision `89899ee3b0719d73f36311004ac32f87e8a78dee`)

### Request planning path versus execution path

The inspected request-planning path is:

```text
SearchAgentRequestHandler.plan
  -> TopLevelRouter.classify
  -> CandidateEvidenceProvider.get
  -> TopLevelRouter.plan
  -> SearchRun + ToolCall("web.search", ...)
```

This path creates a tool-call plan; the inspected `request_handler.py` does not itself execute the returned `ToolCall`. It must not be mistaken for proof that a web search was actually performed.

The separate execution path in `SearchAgentOrchestrator.execute_request` is:

```text
AdaptiveSearchPlanner.plan
  -> injected search_executor(query)
  -> SearchRuntime.execute(run, source_refs)
  -> save traces
  -> _to_assessment + assess_result
  -> RegistryWriteProposal(approval_required=False)
  -> registry_writer.execute(proposal)
  -> save_registry_result
  -> if status == READY_TO_MUTATE: UserRegistry.enroll
  -> record utility/feedback/search run
  -> SearchScreeningLoop.evaluate_and_adapt
  -> persist metric update and validation
```

This path is **callable source code**, but the available evidence does not establish that a production trigger constructs the dependencies and invokes it with a real authorized search adapter. `SourceAcquisition` is a separate injected contract and is not directly invoked in the shown `execute_request` method; the method receives `search_executor` directly.

### Fail-open projection and authorization findings

- `SearchAgentOrchestrator._to_assessment` defaults missing `decision_source_verified` to `True`, missing `privacy_ok` and `schema_ok` to `True`, and missing `duplicate_conflict` to `False`. Missing attributes therefore become success-shaped decisions.
- The constructed `RegistryWriteProposal` sets `approval_required=False`. When the writer returns `READY_TO_MUTATE`, the orchestrator enrolls the opportunity in `UserRegistry`.
- `RecruitmentFlow._analysis_metadata` synthesizes missing records with `total_score=0.0`, `duplicate_free=True`, `privacy_ok=True`, and `schema_ok=True`. These are not supported by the absence of data and must be represented as UNKNOWN/unverified.
- `domain_adapters.evidence_validation_service` calls `bool(row.get("privacy_ok", True))` and `bool(row.get("schema_ok", True))`, repeating the fail-open defaults at an adapter boundary.
- The top-level router defaults to policy version `v5.4.13` in the inspected file, while the reviewed active repository instruction is `v5.4.25`. This is version drift; it does not alone establish the effective production version.

### Target rebuild implications

1. The new runner must be called by a known entry point; planning a `ToolCall` is not an execution receipt.
2. Search adapters must return structured acquisition receipts and provenance, not arbitrary strings that later become source evidence by presence alone.
3. Verification, privacy review, schema validation and duplicate resolution must be explicit tri-state or typed decisions. Missing fields cannot default to success.
4. Registry eligibility/recommendation, private persistence, and external mutation must be separate operations with separate authorization.
5. The target must record stage-level receipts, including the bounded run endpoint, before any persistence or external mutation is considered.
6. No legacy candidate records or assessment outputs are needed to preserve these behaviors; synthetic tests can exercise the contracts.
