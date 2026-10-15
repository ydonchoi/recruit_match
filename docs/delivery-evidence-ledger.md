# Delivery Evidence Ledger

- Snapshot time: 2026-10-15
- Target repository: `ydonchoi/recruit_match`
- Target branch: `bootstrap/verification-first-architecture`
- Target source snapshot before this ledger update: `918d3bd63fca575e25539618c30ee31ea7e9e302`
- Legacy source snapshot: `ydonchoi/recruitment_matching@89899ee3b0719d73f36311004ac32f87e8a78dee`
- PR: [#1](https://github.com/ydonchoi/recruit_match/pull/1), Draft, not merged

## Evidence levels

- **PRESENT**: file or Git object was retrieved from the named repository/ref.
- **SOURCE-REVIEWED**: source text was inspected; this is not runtime proof.
- **TEST-AUTHORED**: test functions are present in the source.
- **TEST-EXECUTED**: an actual execution log exists for the exact revision.
- **UNVERIFIED**: no sufficient evidence is available.

## Target artifact inventory

Blob SHA values are Git blob identifiers from the target snapshot tree. They identify exact tracked file content; they are not SHA-256 checksums of the file bytes.

| Artifact | Git blob SHA | Evidence status |
|---|---|---|
| `src/recruit_match/domain.py` | `bbc45b509e0a69bc05df69e2f194ccd412a21333` | PRESENT / SOURCE-REVIEWED |
| `src/recruit_match/assessment.py` | `659e53dd37d1be0edd2f34aae7a247375c1b350a` | PRESENT / SOURCE-REVIEWED; hard eligibility failures excluded before ranking |
| `src/recruit_match/assessment_handlers.py` | `0ab1edfe6493a6b0959d8fb519d84e131c772dc5` | PRESENT / SOURCE-REVIEWED; recommendation gates derived from upstream context |
| `src/recruit_match/pipeline.py` | `daecba5b74738c4a5d2e2ffff2f632bf3f29248b` | PRESENT / SOURCE-REVIEWED; explicit evidence-required stage flag |
| `src/recruit_match/runner.py` | `c7710783a25eb722fee1baf31b5072f758a62806` | PRESENT / SOURCE-REVIEWED; blocks evidence-required stages without refs |
| `src/recruit_match/workflow.py` | `c6f4c6e01cec500a287dd5d2383f5463b373d582` | PRESENT / 18-stage contract; external live adapters not configured |
| `src/recruit_match/attachments.py` | `b5426827cc929ba812c7b76c93b1d343729cda07` | PRESENT / SOURCE-REVIEWED; DNS-pinned default transport, execution unverified |
| `tests/test_domain.py` | `c5b3b041d846f6dd6020b3fb1e225dc8ae2754d6` | PRESENT / 11 test functions authored |
| `tests/test_assessment.py` | `cf3fd60834fbdf2429e4b5b4aceee436d2b91d8c` | PRESENT / 21 test functions authored |
| `tests/test_assessment_handlers.py` | `9874983de7e67e5c68217fce497a721af9347573` | PRESENT / 8 test functions authored |
| `tests/test_pipeline.py` | `6844fbdbd757c7b70731f0cb8d4e0aa835bb55eb` | PRESENT / 11 test functions authored |
| `tests/test_runner.py` | `f6eef13de79dc4c68ac7380500d0c09b5da3c9f1` | PRESENT / 7 test functions authored |
| `tests/test_attachments.py` | `b10878fca3b84176ea9224419f0cc84945f069f5` | PRESENT / 16 test functions authored |
| `tests/test_workflow.py` | `8930c7caa7c32dcb8c4dbfd100c736468aff125f` | PRESENT / 10 test functions authored |
| `.github/workflows/unit-tests.yml` | `29b5c93e607bd3d26aa1a5395fe7a7d5d0510bc6` | PRESENT / workflow authored, no usable run |

The seven test files contain **84 declared test functions** by source inspection. This is a count of test definitions, not a count of passing tests.

## Execution evidence

- Local test command documented: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Local execution in this session: **NOT PERFORMED**.
- Six Actions attempts were observed on earlier PR heads:
  - [38714021019](https://github.com/ydonchoi/recruit_match/actions/runs/38714021019), head `48595a9c7ac133694f20ff794d056b467f1be648`, conclusion `failure`.
  - [38714612584](https://github.com/ydonchoi/recruit_match/actions/runs/38714612584), head `67c9e1432e6e8a233d9aa374e050ff6bc9680c73`, conclusion `failure`.
  - [38714988414](https://github.com/ydonchoi/recruit_match/actions/runs/38714988414), head `48b4e9dbc0081e3d6de36f7e1348673d8ca53c5c`, conclusion `failure`.
  - [38715035697](https://github.com/ydonchoi/recruit_match/actions/runs/38715035697), head `83d31005209ae09736fb9fc663969d03469343a9`, conclusion `failure`.
  - [38715712142](https://github.com/ydonchoi/recruit_match/actions/runs/38715712142), head `48e5c8d98710bc0a13b92b6c677927e9037d9f46`, conclusion `failure`.
- The inspected jobs all failed before exposing any steps/logs and reported `runner_id=0` with an empty runner name. This is consistent with runner initialization unavailability, but the exact infrastructure cause is not confirmed by logs. These runs do not establish failed assertions and are not passing test runs.
- [Run 38716289804](https://github.com/ydonchoi/recruit_match/actions/runs/38716289804), head `e68b9adcea9bddf74cb91933465c37037761afaa`, also failed before exposing steps/logs.
- Actions run for current snapshot `918d3bd63fca575e25539618c30ee31ea7e9e302`: none observed at snapshot time.
- Test pass/fail count: **UNKNOWN**.
- End-to-end trigger-to-result test with real external adapters: **NOT PERFORMED**. A synthetic full-contract test is authored but not executed.
- Live search connectivity and production transport behavior: **UNVERIFIED**.
- Live Notion writes, durable persistence, concurrency and recovery: **NOT IMPLEMENTED / UNVERIFIED**.
- Candidate-data deletion from legacy Git history, forks, caches or external stores: **NOT PERFORMED / UNVERIFIED**.

## Implementation notes

- The default attachment transport now resolves and validates public IPs at connection time, connects to the numeric IP, retains the original hostname for TLS SNI/certificate validation, and disables environment proxy discovery. This is source-level implementation evidence only; transport tests have not executed successfully.
- The 18-stage workflow declares evidence-required stages for candidate context, discovery, identity resolution, source verification, currentness, attachment policy/fetch/inspection, recruitment evidence, candidate evidence resolution and revalidation.
- The runner fails an evidence-required stage when no evidence references are returned. The recommendation handler derives eligibility and verification gates from upstream context rather than accepting a separate aggregate that could contradict the eligibility stage.
- Ranking excludes hard eligibility failures before sorting.

## Known blockers before merge or integration

1. Execute the 83 authored tests in an approved environment and retain actual output.
2. Exercise the DNS-pinned transport, including DNS changes, pinned socket target, proxy configuration, TLS hostname mismatch and controlled redirects.
3. Connect external search, candidate-context, identity-resolution, source-verification, currentness, attachment and evidence handlers to the 18-stage workflow with authorized adapters and evidence-bearing receipts.
4. Execute the synthetic full-contract test, then add a true integration test with controlled adapters.
5. Decide and approve the private canonical data store, field minimization, access control, retention and deletion semantics before enabling writes.
6. Complete the source call graph and audit relevant callers, test fixtures, CI workflows and sensitive-data paths.

## Interpretation

Repository content presence is not test evidence. A written test is not a passing test. A synthetic contract run would not establish live integration, security, privacy compliance or production readiness. The Draft PR must remain unmerged until blockers are resolved or explicitly accepted by an authorized maintainer with evidence.
