# Target Architecture

Status: **PROPOSED; legacy architecture inventory is partial; not production validated**.

## Governing approach

Review the entire legacy architecture before deciding the target data model or implementation sequence. Each legacy component must be assigned a documented disposition: KEEP, REFACTOR, REBUILD, RETIRE, or UNASSESSED. A source document or code file alone is not proof that a capability is operational.

See [migration-map.md](migration-map.md) for the current source-backed inventory and known gaps, [pipeline-execution-trace.md](pipeline-execution-trace.md) for the partial stage trace, and [data-boundary-decision.md](data-boundary-decision.md) for persistence boundaries.

## Provisional component boundaries

- **Access and privacy governance:** policy gates before acquisition or mutation.
- **Domain:** typed records and invariants, independent of network/persistence.
- **Pipeline orchestration:** explicit stage contracts, prerequisites, attempts, terminal outcomes, and lineage.
- **Evidence/provenance:** source identity, observation time, verification status, uncertainty, and evidence separation.
- **Assessment:** requirement-level eligibility, fit, compensation and recommendation contracts.
- **Registry/write governance:** explicit eligibility, approval, mutation intent, idempotency, and result evidence.
- **Persistence:** durable state and transaction boundaries to be selected after failure-mode analysis.
- **Outbox/worker:** planned asynchronous delivery; durable before acknowledgement, replayable after restart.
- **Adapters:** Notion is a candidate future persistence adapter, blocked pending schema/access review. GitHub registry CRUD and registry-sync adapters are out of scope by default; GitHub hosts code and sanitized engineering artifacts only.
- **Human decision/execution boundary:** automated analysis must not silently become a human decision or application submission.
- **Verification ledger:** planned record of test executions, external mutations, retries, and reconciliation outcomes.

These are target boundaries, not a claim that the full pipeline is implemented.

## Registry and GitHub boundary

GitHub registry create/update/delete and registry-sync are not part of the default target architecture. The analysis pipeline and logical Registry domain may remain, but persistence belongs in an approved private store. Notion is a candidate store only after schema, access, retention and field-minimization review. See [data-boundary-decision.md](data-boundary-decision.md).

## Intended event path (provisional)

`AnalysisCompleted` -> validate bounded run and stage prerequisites -> persist proposal plus outbox item atomically -> worker claims item -> idempotent adapter operation -> read-back/reconcile -> persist observed result and evidence.

This path is a design proposal. Its storage, locking, retry, conflict, and delivery guarantees remain to be specified.

## Failure cases to resolve before external integration

1. External write succeeds but local acknowledgement fails.
2. Worker crashes after claiming an item.
3. Two workers process the same idempotency key.
4. Notion returns rate limits, transient server errors, schema errors, or permission errors.
5. Query returns duplicate records or multiple pages.
6. A Notion property is absent, renamed, or has a different type.
7. A record changes while a stale update is in flight.
8. A mandatory pipeline stage has no valid terminal outcome.
9. A run stops at a bounded endpoint and is later resumed.
10. A material change invalidates a prior assessment or recommendation.

No live Notion writes should be enabled until these cases have explicit contracts and tests. The domain model remains provisional until the legacy inventory and migration decisions have been reviewed.
