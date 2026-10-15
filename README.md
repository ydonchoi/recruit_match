# recruit_match

A verification-first recruitment registry. The initial implementation deliberately starts small: explicit domain states, fail-closed validation, and tests that can run without GitHub Actions or live Notion credentials.

## Current status

- **Stage:** bootstrap / design baseline
- **Runtime integration:** not implemented
- **Notion writes:** disabled / not implemented
- **GitHub Actions:** not treated as evidence until an actual run is observed
- **Verification:** run the local standard-library test suite with `PYTHONPATH=src python -m unittest discover -s tests -v`

## Design principles

1. Evidence and observed execution results outrank self-reported completion.
2. Missing or unknown values never silently become successful states.
3. Application outcome, execution readiness, lifecycle, and sync status are separate concepts.
4. A test being written is not the same as it passing; unexecuted checks remain `UNVERIFIED`.
5. External adapters must not decide domain truth. They translate data and report failures.
6. External mutations require explicit idempotency and recovery design before production use.

## Repository layout

- `src/recruit_match/domain.py`: minimal domain types and fail-closed validation.
- `tests/`: executable unit tests using the Python standard library.
- `docs/architecture.md`: initial component boundaries and event flow.
- `docs/verification-policy.md`: verification status and evidence rules.
- `docs/data-model.md`: initial domain model and state separation.

## Local development

Python 3.11+ is recommended. No third-party packages are required for the bootstrap test suite.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Passing local tests validates only the code paths those tests exercise. It does not prove live Notion integration, GitHub event wiring, concurrency safety, or production readiness.
