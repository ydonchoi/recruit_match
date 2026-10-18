# Search Agent ToolCall Execution Runbook

- Date: 2026-10-19
- Repository: `ydonchoi/recruit_match`
- Status: prepared for controlled integration testing; **not executed**
- Scope: Search Matrix planning → allowlisted host ToolCall dispatch → normalized result receipts
- Out of scope: candidate-data persistence, application submission, automatic registry writes

## 1. What this runbook validates

The adapter separates three claims that must not be conflated:

1. **Dispatch attempted:** the adapter invoked the injected dispatcher.
2. **Dispatch returned:** the dispatcher returned a response to the adapter. This does not by itself establish that the response is semantically valid.
3. **Response validated:** the injected normalizer produced a sequence of valid `SearchProviderHit` objects.

Official-source authority, currentness, recruitment-cycle identity, eligibility, and recommendation are separate later checks. A normalized search result is not yet an eligible opportunity.

## 2. Static / synthetic contract checks

The intended command is:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The current tests are authored but have not been executed in the development environment. Save the exact command, revision, environment, exit code, and complete output when a run is eventually performed.

The tool adapter tests cover:

- allowlist rejection before dispatch;
- duplicate call ID and duplicate combination rejection before dispatch;
- strict positive-integer budget validation;
- dispatch attempt count never exceeding the budget;
- budget-skipped calls having no dispatch timestamp and no attempt flag;
- dispatcher exceptions being recorded as ambiguous and not retried;
- returned but malformed responses being marked rejected rather than treated as valid results;
- normalized results carrying validated source URLs;
- defensive copies of nested tool arguments;
- integration into the bounded `run_analysis()` path;
- partial discovery stopping the pipeline while preserving diagnostic receipts.

## 3. Controlled host integration procedure

Use a test query and synthetic result data first. Do not use candidate-specific data in the first pass.

1. Choose one allowlisted host tool name. Record its exact identifier and API/schema version if available.
2. Inject the host dispatcher and a result normalizer. The normalizer must reject missing IDs, missing titles, invalid URLs, and unexpected response shapes.
3. Set a small explicit budget, for example two dispatch attempts, and plan more than two combinations.
4. Capture both adapter receipts and the host's own call/request logs.
5. Compare counts. The adapter's `attempted_dispatch_count` counts calls to the injected dispatcher. The host-side log is required to identify nested requests, retries, or fan-out inside that dispatcher.
6. Confirm that the excess planned combinations are `SKIPPED_BUDGET` and were never sent to the dispatcher.
7. Cause one controlled dispatcher timeout. Verify that the adapter records `execution_confirmation=UNKNOWN`, does not retry, and does not claim the external operation definitely failed.
8. Return a malformed payload. Verify that dispatch is recorded as returned while response validation is `REJECTED`.
9. Run a complete synthetic plan within budget. Verify that each planned call has exactly one receipt and that planned/attempted/succeeded/failed/skipped counts reconcile.
10. Run a partial plan through `run_analysis(..., bounded_through="discovery")`. Confirm that downstream stages do not execute when discovery is blocked.

Do not use a real provider until its use is authorized and the provider's request-count semantics are known.

## 4. Evidence capture table

For each test run, record:

| Field | Required value |
|---|---|
| Code revision | Full commit SHA |
| Environment | OS, Python version, dependency lock/version |
| Tool | Exact allowlisted tool identifier |
| Tool schema | Version or captured schema reference |
| Run ID | Unique, non-sensitive ID |
| Planned calls | Integer |
| Adapter dispatch attempts | Integer |
| Host-observed requests | Integer, or UNKNOWN if not exposed |
| Success / failure / skipped | Counts |
| Response validated / rejected | Counts |
| Ambiguous outcomes | Count and call IDs |
| Exit status | Exact process exit code |
| Raw output | File path or immutable evidence reference |
| Reviewer conclusion | PASS / FAIL / INCONCLUSIVE with rationale |

Do not store API keys, auth headers, personal candidate records, or raw private candidate evidence in repository logs.

## 5. Acceptance criteria

A controlled test is acceptable only if:

- the allowlist is enforced before any external call;
- adapter dispatch attempts never exceed the configured budget;
- each planned call has exactly one terminal receipt;
- the report's arithmetic invariants hold;
- no implicit retry occurs after an ambiguous dispatcher exception;
- malformed returned data is not classified as validated;
- budget-skipped calls have no attempt timestamps and no dispatch;
- failed/blocked discovery stops downstream pipeline stages;
- the host-side request count is available or explicitly marked UNKNOWN;
- no result is described as official, current, eligible, or recommended solely because search returned it.

## 6. Current evidence status

- Adapter source exists and has been source-inspected.
- Twelve test functions exist in `tests/test_tool_call_adapter.py`; they are authored only.
- The legacy adaptive-planner bridge has two additional authored tests in `tests/test_search_stage.py`.
- No test execution output is available for this code revision.
- No real host dispatcher, credentials, or provider is configured by default.
- The receipt store is in-memory. Durable audit, cross-process idempotency, concurrency control, and recovery are not implemented.
- Therefore runtime behavior, actual external request counts, and production readiness remain **UNVERIFIED**.
