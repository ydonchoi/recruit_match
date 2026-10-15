# recruit_match

A clean, verification-first reimplementation of the recruitment matching system.

## Project approach

**Review the whole legacy architecture first; then selectively migrate, redesign, rebuild, or retire each component.** This project is not limited to moving the data model, and it will not blindly copy the legacy implementation.

- Legacy source: [ydonchoi/recruitment_matching](https://github.com/ydonchoi/recruitment_matching)
- Current migration inventory: [docs/migration-map.md](docs/migration-map.md)
- Target architecture: [docs/architecture.md](docs/architecture.md) (proposed; not production validated)
- Initial domain model: [docs/data-model.md](docs/data-model.md) (provisional, not canonical)

## Verification principles

1. Evidence and observed execution results outrank self-reported completion.
2. Missing or unknown values never silently become successful states.
3. Application outcome, execution readiness, lifecycle, and sync status are separate concepts.
4. A test being written is not the same as it passing; unexecuted checks remain unverified.
5. External adapters translate data and report failures; they do not invent domain truth.
6. External mutations require explicit idempotency and recovery design before production use.
7. Runtime integration is not complete until the trigger-to-result path is demonstrated end-to-end.

## Current status

- **Stage:** architecture inventory and migration planning
- **Runtime integration:** not implemented
- **Notion writes:** not implemented
- **GitHub Actions:** no successful run claimed
- **Verification:** local standard-library tests can be run with `PYTHONPATH=src python -m unittest discover -s tests -v`

## Repository layout

- `src/recruit_match/domain.py`: provisional domain types and fail-closed validation.
- `tests/`: executable unit tests for the bootstrap domain.
- `docs/migration-map.md`: source-backed, partial legacy architecture inventory and migration decisions to be completed.
- `docs/pipeline-execution-trace.md`: partial trace of legacy pipeline and selected implementation paths.
- `docs/data-boundary-decision.md`: no-GitHub-registry-sync decision and data placement rules.
- `docs/architecture.md`: target boundaries and intended event path.
- `docs/verification-policy.md`: verification statuses and evidence rules.
- `docs/data-model.md`: provisional state model.

## Local development

Python 3.11+ is recommended. The bootstrap test suite uses only the Python standard library.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Passing local tests validates only the code paths those tests exercise. It does not prove live Notion integration, GitHub event wiring, concurrency safety, or production readiness.
