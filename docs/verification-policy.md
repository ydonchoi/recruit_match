# Verification and evidence policy

Status: **PROPOSED; effective for this bootstrap until replaced explicitly**.

## Separate statuses

- `NOT_WRITTEN`: no test or check exists.
- `WRITTEN_NOT_RUN`: test exists but has not been executed.
- `PASSED_LOCAL`: executed locally and passed; scope is limited to the recorded command and environment.
- `FAILED`: executed and failed; preserve the failure output.
- `BLOCKED`: cannot run because a dependency, credential, permission, or external service is unavailable.
- `PASSED_CI`: the relevant CI run actually completed successfully; a workflow file or badge alone is not evidence.
- `UNVERIFIED`: current behavior lacks sufficient evidence.

## Required evidence per change

1. Change identifier and affected invariant.
2. Test(s) added or updated.
3. Exact command and environment used.
4. Actual result and relevant output.
5. Uncovered paths and residual risks.
6. Whether the change is safe to merge or enable in production.

## Non-negotiable distinctions

- A test file existing does not mean the test passed.
- A local pass does not prove CI passed.
- A CI pass does not by itself prove live external integration works.
- A source URL being present does not mean it was verified.
- An API write response does not by itself prove the final stored state is correct; read-back or reconciliation is needed where feasible.
- Unknown, missing, or blocked evidence must remain visible and must not be converted to success-shaped defaults.
