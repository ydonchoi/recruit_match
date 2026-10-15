# Initial architecture baseline

Status: **PROPOSED; not production validated**.

## Component boundaries

- **Domain:** typed records and business invariants; no network or persistence dependencies.
- **Validation:** explicit checks that return structured issues. Unknown is not success.
- **Repository/store:** durable persistence contract to be selected after requirements and failure modes are specified.
- **Outbox/worker:** planned asynchronous delivery boundary. It must persist work before acknowledging it and support replay after process restart.
- **Notion adapter:** planned translation layer only. It must not silently infer domain state from missing Notion properties.
- **Evidence ledger:** planned append-only record of test executions, external mutations, retries, and reconciliation outcomes.

## Intended event path

`AnalysisCompleted` -> validate proposal -> persist proposal and outbox item atomically -> worker claims item -> idempotent adapter operation -> read-back/reconcile -> persist observed result and evidence.

This is a target design, not an implemented or tested end-to-end flow.

## Failure cases to design before integration

1. The external write succeeds but local acknowledgement fails.
2. The worker crashes after claiming an item.
3. Two workers process the same idempotency key.
4. Notion returns rate limits, transient server errors, schema errors, or permission errors.
5. A query finds duplicate records or more results than one page.
6. A Notion property is absent, renamed, or has a different type.
7. A record changes while a stale update is in flight.

No live Notion writes should be enabled until these cases have explicit contracts and tests.
