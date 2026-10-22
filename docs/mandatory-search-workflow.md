# Mandatory Search Execution, Logging, and Validation Workflow

Status: Proposed operational gate
Scope: All recruitment-search runs in this repository, including repeated/expanded searches.
Authority: This workflow governs execution and reporting; it does not prove a run happened unless the run log contains evidence.

## Non-negotiable rule

A search run MUST NOT be reported as complete unless its execution log and result records have been written and checked. A planned search, a conversational description, or a list of suggested platforms is not execution evidence.

## Required execution sequence

1. Create a run record before searching.
2. Search the registered baseline platforms and any approved expansion sources. Keep the baseline platform set in scope unless access is blocked; record each platform's status.
3. Record every query/axis actually executed, timestamp, source/platform, result URL or source reference, result count when available, and success/failure/blocked status.
4. Save each found posting to the cumulative ledger. Deduplicate by official posting URL or stable posting identifier; retain alternate source URLs.
5. For existing postings, append a verification event rather than creating a duplicate. Track application status, deadline, eligibility evidence, and last-checked time.
6. Validate each candidate against the official posting. Use verified, partially_verified, unverified, closed, or excluded status; record evidence and reason.
7. Reconcile run totals: raw results where measurable, unique postings, duplicates, newly added postings, changed postings, closed postings, and unverified postings.
8. Only after steps 1–7 may the run be marked completed. If any mandatory step is blocked, mark it partially_completed or blocked, explain why, and do not claim full coverage.
9. At final reporting, separate: (a) run coverage/logs, (b) cumulative ledger, (c) verified open candidates, and (d) excluded/unverified records with reasons.

## Required artifacts

Maintain these machine-readable artifacts in the working environment or repository:
- logs/search_runs.jsonl: one JSON object per actual run.
- data/postings.jsonl: one canonical record per unique posting.
- data/posting_events.jsonl: append-only discovery, verification, deadline/status change, deduplication, and exclusion events.
- reports/latest_run_summary.md: summary generated from recorded data, not manually estimated.

Do not claim these artifacts exist until they have been created and verified. If a platform does not expose a reliable result count, record null and the limitation instead of estimating.

## Minimum schemas

### Search run (logs/search_runs.jsonl)

    {
      "run_id": "YYYYMMDD-HHMMSS-unique",
      "started_at": "ISO-8601 with timezone",
      "ended_at": "ISO-8601 with timezone or null",
      "iteration": 1,
      "platform": "platform name",
      "query_axes": ["job title", "institution type"],
      "queries_executed": ["exact query string"],
      "status": "completed | partially_completed | blocked",
      "raw_result_count": null,
      "new_postings": 0,
      "duplicates": 0,
      "updated_postings": 0,
      "errors_or_limitations": [],
      "evidence_urls": []
    }

### Canonical posting (data/postings.jsonl)

    {
      "posting_id": "stable local identifier",
      "institution": "institution",
      "title": "job title",
      "official_url": "https://...",
      "alternate_source_urls": [],
      "location": "location or null",
      "employment_type": "regular | contract | fixed_term | other | unknown",
      "opened_at": null,
      "deadline_at": null,
      "application_status": "open | closed | unknown",
      "eligibility_status": "verified | partially_verified | unverified | not_eligible",
      "fit_assessment": "high | review | low | unassessed",
      "eligibility_evidence": [],
      "first_seen_run_id": "run id",
      "last_checked_at": "ISO-8601 or null",
      "last_checked_run_id": "run id or null"
    }

### Posting event (data/posting_events.jsonl)

Each event must include event_id, posting_id, run_id, event_type, occurred_at, evidence_urls, and notes. Events are append-only; do not erase historical status changes.

## Completion gate

Before claiming a batch or 20-iteration sequence is complete, verify:
- Every required platform/iteration has a run record or an explicit blocked/skipped reason.
- Every run record corresponds to a real search execution.
- All discovered postings are in the canonical ledger or have a documented exclusion reason.
- Duplicate counts and status totals reconcile with the ledger/events.
- All recommended postings have official-source evidence for current application status and eligibility, or are explicitly labelled unverified.
- The report's counts are computed from the stored records.
- Missing logs, unavailable platforms, and unverified eligibility are disclosed.

A 20-iteration plan is not a 20-iteration completion. Mark only actually executed iterations as completed.