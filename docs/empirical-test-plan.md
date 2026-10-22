# Empirical-test-first operating plan

Status: **Test harness configured; no live-source run is implied by this document.**
Target: `ydonchoi/recruit_match` only.
Baseline scope: the 12 entries in `run_pipeline.py::BASELINE_PLATFORMS`.

## Test layers and evidence

| Layer | What it proves | How to run | What it does not prove |
|---|---|---|---|
| Static compilation | Selected Python modules parse | `python -m compileall -q run_pipeline.py search_engine.py search_orchestrator.py analysis_pipeline.py analysis_services.py adapters tests` | Correct runtime behavior or external connectivity |
| Offline unit/contract tests | Fail-closed configuration, adapter registry coverage, analysis invariants | `python -m unittest discover -s tests -v` | Live search results, current vacancies, or terms permission |
| Config readiness | Required endpoint, token and host allowlists are syntactically present | Run tests or call the relevant `readiness()` functions | Network reachability, credentials accepted, source coverage |
| Live baseline smoke test | One real query was attempted against each baseline adapter and the observed run was logged | GitHub Actions → **Empirical integration tests** → Run workflow → set `run_live_smoke=true` | Exhaustive search, official-posting verification, candidate eligibility, or 20 iterations |
| Official-posting validation | A specific result is supported by the official posting, deadline and eligibility evidence | Inspect `data/postings.jsonl`, `data/posting_events.jsonl`, `data/analysis_results.jsonl` and official URLs | Any fact not evidenced in those artifacts |

## Required secrets for the opt-in live smoke test

Configure these as GitHub Actions repository or environment secrets; never commit values:

- `RECRUIT_MATCH_SEARCH_ENDPOINT`
- `RECRUIT_MATCH_SEARCH_API_KEY`
- `RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS`
- `RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL`
- `RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS`
- `RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN`

The search endpoint must implement the documented Bing Web Search-compatible response shape. The analysis service must implement all three contracts documented in `docs/operations-readiness.md`. If any secret is missing, the live job stops in preflight and must be reported as **BLOCKED**, not as zero results or successful testing.

HTML crawling remains disabled unless a reviewed `RECRUIT_MATCH_CRAWL_CONFIG_JSON` is provided. Do not set `terms_reviewed: true` until an operator has actually reviewed the applicable terms and crawl policy for each listed site. Robots.txt alone is not permission.

## Execution protocol

1. Run the offline workflow first; preserve the Actions run URL and commit SHA.
2. Add the six secrets only after the endpoints, ownership, contract and policy have been reviewed.
3. Manually dispatch the live smoke job with `run_live_smoke=true`. It uses one planned query and the existing baseline orchestration; it is intentionally low-volume.
4. Download the `recruit-match-live-smoke-evidence` artifact. Check run ID, timestamps, query, all 12 platform statuses, raw result count, errors, official URLs and analysis-stage status.
5. For each platform, classify evidence as `COMPLETED`, `PARTIALLY_COMPLETED`, `BLOCKED` or `FAILED`. A completed adapter call means only that the configured search adapter returned successfully; it does not mean that the platform itself authorized direct crawling or that any posting is verified.
6. Validate candidate details against official posting pages. Keep application status `unknown` and eligibility `unverified` unless the evidence supports stronger values.
7. Do not report full operational success unless the run logs/artifacts reconcile and the canonical analysis pipeline completes without unresolved blockers.

## Current state

- Offline tests: **not yet executed in this change**; CI result is the verification source.
- Live search: **not executed**; credentials and endpoints have not been supplied in the repository context.
- Official-source verification: **not executed as part of the repository runtime**.
- 12-platform coverage: adapter entries are covered by an offline contract test; this is not proof of 12 live successful searches.
