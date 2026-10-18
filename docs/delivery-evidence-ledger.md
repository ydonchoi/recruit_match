# Delivery Evidence Ledger

- Snapshot date: 2026-10-19
- Target repository: `ydonchoi/recruit_match` (private)
- Target branch: `bootstrap/verification-first-architecture`
- Target branch head before this ledger update: `35a515ec397aa933be34e009aaae2c2c80fa4828`
- Legacy source revision: `ydonchoi/recruitment_matching@89899ee3b0719d73f36311004ac32f87e8a78dee`
- PR: [#1](https://github.com/ydonchoi/recruit_match/pull/1), Draft, not merged

## Evidence levels

- **PRESENT**: file or Git object was retrieved from the named repository/ref.
- **SOURCE-REVIEWED**: source text was inspected; this is not runtime proof.
- **TEST-AUTHORED**: test functions are present in source.
- **TEST-EXECUTED**: an actual execution log exists for the exact revision.
- **UNVERIFIED**: no sufficient evidence is available.

## Implementation snapshot

| Artifact | Git blob SHA | Evidence status |
|---|---|---|
| `src/recruit_match/domain.py` | `30defb62612f32e07c3b19cfb8dbeb7a827367fa` | PRESENT / SOURCE-REVIEWED; canonical currentness enum aligned with recommendation policy |
| `src/recruit_match/assessment.py` | `afbedb21fde8c62c298c510d55904a0eb9ae6f9f` | PRESENT / SOURCE-REVIEWED; typed currentness, duplicate-ID checks, stricter requirement evidence contract |
| `src/recruit_match/assessment_handlers.py` | `9cdb686c54ec8c4de1950935174ea1753b7a2b92` | PRESENT / SOURCE-REVIEWED; recommendation gates derived from upstream context and typed currentness |
| `src/recruit_match/pipeline.py` | `febb2053779d3a98610c607f2d03c94cbb009fb5` | PRESENT / SOURCE-REVIEWED; strict stage and receipt contracts |
| `src/recruit_match/runner.py` | `d3c3c293d0729615a19cf45b7210dd3795807d90` | PRESENT / SOURCE-REVIEWED; malformed handler output fails closed |
| `src/recruit_match/workflow.py` | `c6f4c6e01cec500a287dd5d2383f5463b373d582` | PRESENT / 18-stage contract; real adapters not configured |
| `src/recruit_match/application.py` | `8d0318d8689b28ba7655d7d692c9f8c03cb11147` | PRESENT / SOURCE-REVIEWED; injectable full/bounded entry point |
| `src/recruit_match/search_execution.py` | `fd6cb37dd320e25faf3ca9a87b6b5f3cd36b79c6` | PRESENT / SOURCE-REVIEWED; Search Matrix-shaped plan adapter, hard callable-invocation budget, per-query in-memory receipts; no provider configured |
| `src/recruit_match/search_stage.py` | `2044f16d8142644dfea22d3fe639cc1b3889633d` | PRESENT / SOURCE-REVIEWED; injected plan/discovery factories plus legacy adaptive planner bridge; no default provider |\n| `src/recruit_match/tool_call_adapter.py` | `76dfbe1e01fed01d1601532b614d09fa6983590e` | PRESENT / SOURCE-REVIEWED; allowlisted host ToolCall dispatch, hard budget, separate execution/response states; no host tool configured |\n| `src/recruit_match/tool_call_adapter.py` | `76dfbe1e01fed01d1601532b614d09fa6983590e` | PRESENT / SOURCE-REVIEWED; allowlisted host ToolCall dispatcher, hard dispatch budget, separate execution/response states; no host tool configured |

| `src/recruit_match/attachments.py` | `9c0af749e909ec59e8bbcfd1a17fa3efbcb13359` | PRESENT / SOURCE-REVIEWED; typed policy flags and malformed DNS responses rejected; transport execution unverified |
| `docs/adapter-contracts.md` | `363ec30ce07ac6ea2251d97b00d3046414901d91` | PRESENT / defines adapter responsibilities, direct ToolCall dispatch and receipt states |\n| `docs/tool-call-execution-runbook.md` | `2609d9c002bab9e843117547595ae0e0b4f5d81e` | PRESENT / controlled integration test procedure and acceptance criteria; not executed |\n| `README.md` | `b66f0074e2eb44a7d4e5e4cb81a83b2ebb5adef2` | PRESENT / links runbook; 160 authored test functions documented |
| `docs/architecture.md` | `50d7d8ea2d73b9e3b9e97dbb217f9b74fa0c6aa1` | PRESENT / architecture status updated |
| `docs/legacy-architecture-inventory.md` | `aba47610afa4586f4da68c6020b12b8db011fa1a` | PRESENT / complete tracked-path inventory, partial call graph |
| `docs/target-architecture-and-migration-plan.md` | `1166785636961e63e8c6e7dbabde5e8fa5b4704b` | PRESENT / partial implementation status |
| `docs/static-review-and-migration-status.md` | `1e728c2fa4ab8170fd62c18fb5323fdb91923ef3` | PRESENT / static findings, migration disposition, legacy call-path, metric risks and search execution bridge; no execution claimed |
| `.github/workflows/unit-tests.yml` | `29b5c93e607bd3d26aa1a5395fe7a7d5d0510bc6` | PRESENT / workflow definition only |

## Authored test inventory

| Test file | Git blob SHA | Test functions |
|---|---|---:|
| `tests/test_domain.py` | `475a44ec268f4610a31daeb9f22cf62649bb34b9` | 14 |
| `tests/test_assessment.py` | `b64617a5944861525bb379e44127dcaaba9e8adb` | 34 |
| `tests/test_pipeline.py` | `cf45abcc382306e69bd43f51dc87716c71b76b3a` | 16 |
| `tests/test_runner.py` | `6744b0316ea64e37ab27bd38a9c7b34f15f59900` | 13 |
| `tests/test_attachments.py` | `fed630df097903273229d1ca29bf7b63030c1c19` | 22 |
| `tests/test_workflow.py` | `42aa6a5a64f2d49eea1a4df6fe0ea6959bdbfd1d` | 10 |
| `tests/test_assessment_handlers.py` | `4b925b009e484b7c657619f3aa976b0eda2b765d` | 9 |
| `tests/test_application.py` | `b525c98df09b67f8397c5e92f9045197ee9a93c9` | 4 |
| `tests/test_search_execution.py` | `8054cc3e1b66b37aa93a051da31baca39265b386` | 12 |
| `tests/test_search_stage.py` | `9d3e5b47989d2470ae40e25703757886ecbcb2a7` | 12 |
| **Total** | | **146** |

This is a count of declared test functions by source inspection, not a count of passing tests.

## Execution evidence

- Documented test command: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Local execution of that command: **NOT PERFORMED**.
- A separate browser-shell execution attempt could not start a clone because that environment has no `git` executable. The Python test command was not reached; this is not a test result.
- GitHub Actions attempts repeatedly fail before exposing test steps. The latest run observed during this review was [38720734931](https://github.com/ydonchoi/recruit_match/actions/runs/38720734931), for code-bearing head `272d500741e703620a2a13e0ebca0e6f63a1428c`. Its job reports `runner_id=0`, empty runner name and no steps. The same pattern is present in the immediately preceding attempts. This observation is not a test result.
- The observed pattern is consistent with runner initialization unavailability, but the exact infrastructure cause is not confirmed by logs.
- No test assertion output is available. Test pass/fail count: **UNKNOWN**.
- The synthetic full-workflow test calls the public `run_analysis` entry point, but it has **not been executed**.
- Live search, source verification, attachment transport, external Notion access/writes, durable persistence, concurrency/recovery and end-to-end production behavior: **UNVERIFIED / NOT IMPLEMENTED**.
- Candidate-linked data was not copied into the new repository. Legacy history, forks, caches, CI artifacts and external copies have not been exhaustively audited or erased.

## Static review changes (2026-10-15)

- Added `CurrentnessState.CLOSING_SOON` and `CurrentnessState.EXPIRED` so the domain vocabulary matches the recommendation policy recognized states.
- Recommendation inputs and the assessment handler now require the canonical `CurrentnessState` enum instead of accepting arbitrary strings.
- Eligibility evaluation now rejects malformed collections and duplicate requirement IDs; a critical requirement needs both candidate and recruitment evidence domains plus at least two distinct evidence references before its status can decide eligibility.
- Ranking rejects duplicate opportunity IDs rather than silently allowing ambiguous duplicate entries.
- Attachment policy flags must be booleans; DNS resolver output is shape-validated and malformed socket-address tuples return a sanitized policy error.
- Added eight test functions covering these boundaries. They are authored only; **not executed**. Current authored test count: 160.

## Search execution budget evidence (2026-10-19)

- Added `src/recruit_match/search_execution.py` to adapt Search Matrix-shaped combinations (`combination_id`, `query`) to a budgeted injected callable.
- Each planned query receives one in-memory receipt: success, failure, or budget-skipped. The report validates planned/attempted/succeeded/failed/skipped arithmetic and refuses duplicate ordinals or combination IDs before calls.
- Added `tests/test_search_execution.py` with 12 authored test functions covering budget enforcement, call/receipt reconciliation, provider failure, duplicate plans, and the Search Matrix adapter bridge.
- These 12 tests have **not been executed**. The counter measures invocations of the injected callable only; provider-internal retries, fan-out, and external calls outside the boundary require separate instrumentation.
- No real Search Matrix planner, search provider, tool API, or durable receipt store is connected to this module. Actual Search Agent activation and real-world call-count compliance remain **UNVERIFIED**.

## Current architecture evidence

- `src/recruit_match/application.py` provides an explicit full/bounded entry point and uses injected stage handlers. Missing adapters fail closed at the first unconfigured required stage.
- `docs/adapter-contracts.md` defines responsibilities and receipt requirements for external source, candidate-context, identity, verification, attachment, evidence and revalidation adapters.
- The runner validates stage definitions, typed outcomes, reference shapes, predecessor relationships, bounded scope and required evidence-reference presence.
- A non-empty evidence reference is a pointer, not proof that the referenced content is authoritative or verified. Adapters must return explicit verification states.
- The default attachment transport pins the connection to a validated numeric public IP while preserving the hostname for TLS. Tests are authored, but actual network behavior and adversarial cases are not verified.
- No approved private canonical store has been selected. Notion remains blocked pending access, field minimization, retention, deletion and identity/conflict review. GitHub Registry CRUD/sync is out of scope by default.

## Remaining merge/integration gates

1. Execute all 160 authored tests and retain actual output.
2. Exercise the DNS-pinned transport with TLS hostname mismatch, controlled redirects, IPv4/IPv6, DNS changes and proxy configuration.
3. Implement and authorize actual external stage adapters; verify each adapter's source identity, observation time, access basis and evidence receipts.
4. Execute the synthetic full workflow through `run_analysis`, then integration tests with controlled adapters.
5. Approve private persistence, data minimization, access, retention and deletion semantics before any live write.
6. Complete source-content and caller tracing for the legacy implementation; the 1,059-path inventory is complete, but the call graph is partial.
7. Review the complete PR diff and all execution outputs before removing Draft status.

## Interpretation

Repository content presence is not runtime evidence. Authored tests are not passing tests. A synthetic run would not establish live provider integration, privacy compliance, transport security or production readiness. Keep PR #1 in Draft until the merge gates are resolved or explicitly accepted with evidence by an authorized maintainer.


## Search stage implementation addendum (2026-10-19)

- `src/recruit_match/search_stage.py` defines injected `search_plan` and `discovery` stage handlers. It does not select a provider or planner by default.
- `tests/test_search_stage.py` adds 12 test functions; `tests/test_runner.py` adds one test to preserve diagnostics from a blocked stage while still stopping downstream execution.
- Current authored test inventory is 160 functions across eleven test files. This count is based on source inspection; none of these tests is claimed to have run.
- The search stage can be composed into `run_analysis()` by passing `build_search_handlers(...)` with the caller's request-scope and candidate-context handlers. Actual provider connectivity, provider-internal call counts, and runtime behavior remain unverified.


## Direct host ToolCall adapter (2026-10-19)

- Added `src/recruit_match/tool_call_adapter.py` to dispatch explicit tool-call plans through an injected host dispatcher. Tool names are allowlisted before any dispatch; duplicate call IDs, ordinals, and combination IDs are rejected before side effects.
- The dispatch budget counts invocations of the injected dispatcher. A returned response means dispatch returned, not that the content is authoritative. A dispatcher exception is recorded as an ambiguous `UNKNOWN` external outcome and is not retried automatically.
- Response validation is tracked separately from dispatch confirmation. Malformed returned responses are recorded as rejected, while valid normalized results become `SearchProviderHit` records. Receipt accounting reconciles plan, attempt, success, failure, skip, confirmation and validation counts.
- Added `tests/test_tool_call_adapter.py` with 12 test functions; added two tests for the legacy adaptive-planner bridge in `tests/test_search_stage.py`. All are authored, not executed.
- Added `build_adaptive_planner_callback(...)` in `search_stage.py` to adapt the legacy `AdaptiveSearchPlanner.plan(candidate_evidence, user_query)` interface without importing the legacy package. Candidate-evidence access and planner instances remain explicitly injected.
- No host tool, credentials, real legacy planner instance, or persistent receipt store is configured. Actual tool-call counts, nested provider retries/fan-out, source authority, and end-to-end behavior remain unverified.
