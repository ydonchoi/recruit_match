# Initial domain model

Status: **PROPOSED; not production validated**.

## Independent state dimensions

| Dimension | Initial type | Meaning |
|---|---|---|
| Lifecycle | `UNKNOWN`, `ACTIVE`, `ARCHIVED`, `ON_HOLD` | Whether the opportunity record is currently in scope |
| Application outcome | `UNKNOWN`, `NOT_APPLIED`, `APPLIED`, `INTERVIEWING`, `OFFERED`, `REJECTED`, `WITHDRAWN` | Observed recruitment/application progress |
| Execution readiness | `UNKNOWN`, `BLOCKED`, `READY` | Whether an explicitly defined next action can be executed |
| Sync state | `NOT_CONFIGURED`, `PENDING`, `SYNCED`, `RETRYABLE_FAILURE`, `PERMANENT_FAILURE` | Status of the external projection/synchronization |
| Source verification | Boolean plus source URL | Whether the source itself was checked, not merely recorded |

## Invariants

- No missing lifecycle value is treated as `ACTIVE`.
- Application outcome is not stored in execution readiness.
- A source URL and source verification are separate facts.
- Unknown values are first-class states.
- Scoring and ranking are intentionally excluded from this bootstrap until evidence and eligibility contracts are defined.

This is an initial proposal and may be changed only with a documented rationale and tests.
