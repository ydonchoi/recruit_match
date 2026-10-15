# Delivery Evidence Ledger

- Snapshot date: 2026-10-15
- Target repository: `ydonchoi/recruit_match` (private)
- Target branch: `bootstrap/verification-first-architecture`
- Source snapshot before this ledger update: `f5a6aa978a1fc895dea1191f5935721284e5834c`
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
| `src/recruit_match/domain.py` | `bbc45b509e0a69bc05df69e2f194ccd412a21333` | PRESENT / SOURCE-REVIEWED |
| `src/recruit_match/assessment.py` | `4bfaaddf41df367bede0a1c6f23b156895e730d1` | PRESENT / SOURCE-REVIEWED; strict input checks, hard eligibility exclusion |
| `src/recruit_match/assessment_handlers.py` | `0ab1edfe6493a6b0959d8fb519d84e131c772dc5` | PRESENT / SOURCE-REVIEWED; recommendation gates derived from upstream context |
| `src/recruit_match/pipeline.py` | `be4550aefc19a2a091945a73502ec3152a88a51b` | PRESENT / SOURCE-REVIEWED; strict stage and receipt contracts |
| `src/recruit_match/runner.py` | `35c0aa85deb40e3d76ec8623be61d28976e600eb` | PRESENT / SOURCE-REVIEWED; malformed outputs fail closed |
| `src/recruit_match/workflow.py` | `c6f4c6e01cec500a287dd5d2383f5463b373d582` | PRESENT / 18-stage contract; real adapters not configured |
| `src/recruit_match/application.py` | `8d0318d8689b28ba7655d7d692c9f8c03cb11147` | PRESENT / SOURCE-REVIEWED; injectable full/bounded entry point |
| `src/recruit_match/attachments.py` | `17c472e472ceb659a0c4a5b8a71bb7f4cd2daa39` | PRESENT / SOURCE-REVIEWED; DNS-pinned default transport, execution unverified |
| `docs/adapter-contracts.md` | `c02c1695de8595f8a6b0dad1d624a960d52d7fb7` | PRESENT / defines adapter responsibilities and acceptance gate |
| `docs/architecture.md` | `50d7d8ea2d73b9e3b9e97dbb217f9b74fa0c6aa1` | PRESENT / architecture status updated |
| `docs/legacy-architecture-inventory.md` | `f9cd9230f8ce10de157c1047d5540503df5f83dc` | PRESENT / complete tracked-path inventory, partial call graph |
| `docs/target-architecture-and-migration-plan.md` | `4bc854513f2ed0631dba98637d846190a9bf6cfb` | PRESENT / plan updated to reflect entry point |
| `.github/workflows/unit-tests.yml` | `29b5c93e607bd3d26aa1a5395fe7a7d5d0510bc6` | PRESENT / workflow definition only |

## Authored test inventory

| Test file | Git blob SHA | Test functions |
|---|---|---:|
| `tests/test_domain.py` | `c5b3b041d846f6dd6020b3fb1e225dc8ae2754d6` | 11 |
| `tests/test_assessment.py` | `c1c0f667e64fef2769eafdce6a4fe3aeb1794385` | 27 |
| `tests/test_pipeline.py` | `dcded3eb62a02564d6c021f53e7cde0342029a73` | 14 |
| `tests/test_runner.py` | `fb93138298d67d0581e4e15e1aa35a89cd3e5508` | 8 |
| `tests/test_attachments.py` | `e69624413501faef696a88b600c3c5fc2757794b` | 19 |
| `tests/test_workflow.py` | `f950dca294dd0e1af8d2e58105eee36814b4caf0` | 10 |
| `tests/test_assessment_handlers.py` | `9874983de7e67e5c68217fce497a721af9347573` | 8 |
| `tests/test_application.py` | `b525c98df09b67f8397c5e92f9045197ee9a93c9` | 4 |
| **Total** | | **101** |

This is a count of declared test functions by source inspection, not a count of passing tests.

## Execution evidence

- Documented test command: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Local execution of that command: **NOT PERFORMED**.
- A separate browser-shell execution attempt could not start a clone because that environment has no `git` executable. The Python test command was not reached; this is not a test result.
- GitHub Actions runs repeatedly fail before exposing any test step. The most recent observed run is [38717726097](https://github.com/ydonchoi/recruit_match/actions/runs/38717726097), associated with the same PR and a nearby documentation commit. Its job reports `runner_id=0`, empty runner name and no steps. Earlier runs show the same pattern.
- The latest observed failure is consistent with runner initialization unavailability, but the exact infrastructure cause is not confirmed by logs.
- No test assertion output is available. Test pass/fail count: **UNKNOWN**.
- The synthetic full-workflow test now calls the public `run_analysis` entry point, but it has **not been executed**.
- Live search, source verification, attachment transport, external Notion access/writes, durable persistence, concurrency/recovery and end-to-end production behavior: **UNVERIFIED / NOT IMPLEMENTED**.
- Candidate-linked data was not copied into the new repository. Legacy history, forks, caches, CI artifacts and external copies have not been exhaustively audited or erased.

## Current architecture evidence

- `src/recruit_match/application.py` provides an explicit full/bounded entry point and uses injected stage handlers. Missing adapters fail closed at the first unconfigured required stage.
- `docs/adapter-contracts.md` defines the expected responsibilities and receipt requirements for external source, candidate-context, identity, verification, attachment, evidence and revalidation adapters.
- The runner validates stage definitions, typed outcomes, reference shapes, predecessor relationships, bounded scope and required evidence-reference presence.
- A non-empty evidence reference is a pointer, not proof that the referenced content is authoritative or verified. Adapters must return explicit verification states.
- The default attachment transport pins the connection to a validated numeric public IP while preserving the hostname for TLS. Tests are authored, but actual network behavior and adversarial cases are not verified.
- No approved private canonical store has been selected. Notion remains blocked pending access, field minimization, retention, deletion and identity/conflict review. GitHub Registry CRUD/sync is out of scope by default.

## Remaining merge/integration gates

1. Execute all 101 authored tests and retain the actual output.
2. Exercise the DNS-pinned transport with TLS hostname mismatch, controlled redirects, IPv4/IPv6, DNS changes and proxy configuration.
3. Implement and authorize actual external stage adapters; verify each adapter's source identity, observation time, access basis and evidence receipts.
4. Execute the synthetic full workflow through `run_analysis`, then integration tests with controlled adapters.
5. Approve private persistence, data minimization, access, retention and deletion semantics before any live write.
6. Complete source-content and caller tracing for the legacy implementation; the 1,059-path inventory is complete, but the call graph is partial.
7. Review the complete PR diff and all execution outputs before removing Draft status.

## Interpretation

Repository content presence is not runtime evidence. Authored tests are not passing tests. A synthetic run would not establish live provider integration, privacy compliance, transport security or production readiness. Keep PR #1 in Draft until the merge gates are resolved or explicitly accepted with evidence by an authorized maintainer.
