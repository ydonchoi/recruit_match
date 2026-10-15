# recruit_match

A clean, verification-first reimplementation of the recruitment matching system.

## Project approach

**Review the whole legacy architecture first; then selectively migrate, redesign, rebuild, or retire each component.** This project is not limited to moving the data model, and it will not blindly copy the legacy implementation.

- Legacy source: [ydonchoi/recruitment_matching](https://github.com/ydonchoi/recruitment_matching)
- Migration inventory: [docs/migration-map.md](docs/migration-map.md)
- Tracked-tree inventory and code findings: [docs/legacy-architecture-inventory.md](docs/legacy-architecture-inventory.md)
- Target architecture: [docs/architecture.md](docs/architecture.md) and [docs/target-architecture-and-migration-plan.md](docs/target-architecture-and-migration-plan.md)
- Partial execution trace: [docs/pipeline-execution-trace.md](docs/pipeline-execution-trace.md)
- Data boundary: [docs/data-boundary-decision.md](docs/data-boundary-decision.md)
- Attachment retrieval limits: [docs/attachment-retrieval-boundary.md](docs/attachment-retrieval-boundary.md)
- Verification evidence: [docs/delivery-evidence-ledger.md](docs/delivery-evidence-ledger.md)

## Verification principles

1. Evidence and observed execution results outrank self-reported completion.
2. Missing or unknown values never silently become successful states.
3. Lifecycle, currentness, source verification, eligibility, recommendation, execution readiness and application outcome are separate concepts.
4. A test being written is not the same as it passing; unexecuted checks remain unverified.
5. External adapters translate data and report failures; they do not invent domain truth.
6. External mutations require explicit idempotency and recovery design before production use.
7. End-to-end integration is not complete until the trigger-to-result path is demonstrated.

## Current status

- **Stage:** architecture discovery and initial contract implementation
- **Legacy tracked-tree inventory:** complete for the recorded source revision; full call graph and full file-content review remain partial
- **In-memory stage runner:** implemented as an injectable contract runner; no production handler graph is configured
- **Attachment retrieval:** default transport now connects to a validated numeric IP while retaining TLS hostname verification; execution evidence and live network security remain unverified
- **End-to-end runtime integration:** not implemented
- **Notion writes:** not implemented
- **GitHub Registry CRUD/sync:** excluded from the default target
- **Tests:** 74 test functions are authored across seven test files; execution and results are unverified
- **GitHub Actions:** prior runs failed before any step/log was exposed; the exact infrastructure cause is unconfirmed, and test state remains unknown

## Repository layout

- `src/recruit_match/domain.py`: provisional opportunity domain types and fail-closed validation.
- `src/recruit_match/assessment.py`: pure evidence-gated eligibility, fit scoring, compensation tiering, recommendation and no-padding ranking contracts.
- `src/recruit_match/pipeline.py`: typed stage receipts and fail-closed bounded-run validation.
- `src/recruit_match/runner.py`: injected, in-memory bounded pipeline runner; no production handlers or persistence are configured.
- `src/recruit_match/workflow.py`: canonical 18-stage analysis contract with explicit bounded-run scope.
- `src/recruit_match/assessment_handlers.py`: fail-closed adapters that bind pure assessment functions to the runner; source/search stages still require external handlers.
- `src/recruit_match/attachments.py`: public attachment fetch boundary with allowlist, DNS-pinned HTTPS transport, TLS hostname verification, redirects, robots, time/size limits, MIME/signature checks and integrity receipt. It is not production-ready until tests and adversarial network checks execute successfully.
- `tests/`: synthetic unit tests for domain, stage contracts, runner behavior and attachment safety boundaries.
- `pyproject.toml`: minimal Python package metadata.
- `.github/workflows/unit-tests.yml`: CI definition for later execution; no run is claimed.
- `.gitignore`: excludes local candidate-data directories, credentials, raw source documents and generated run artifacts; this is a guardrail, not a security boundary.

## Local development

Python 3.11+ is recommended. The bootstrap test suite uses only the Python standard library.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Passing local tests validates only the code paths those tests exercise. It does not prove live search connectivity, attachment transport security, Notion integration, persistence concurrency, data deletion or production readiness.
