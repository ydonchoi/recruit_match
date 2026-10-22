# recruit_match

Mandatory recruitment-search workflow and execution gate.

## Run

Requires Python 3.10+; the runner uses only the standard library.

```bash
python run_pipeline.py --iteration 1 \
  --axis "job title" --axis "institution type" \
  --query "교육행정 연구지원 채용" --query "정책연구 행정 채용"
```

The runner writes the run-start record before invoking adapters. It then updates the cumulative posting ledger, appends posting events, and generates `reports/latest_run_summary.md`. Exit code `0` means every baseline platform adapter ran without recorded limitations; exit code `2` means the run is blocked or partially completed. A query passed on the command line is only recorded as executed if an adapter actually receives it.

## Adapter contract

Add one Python module per baseline platform under `adapters/`. Each module must define:
- `PLATFORM`: exact platform name from `BASELINE_PLATFORMS` in `run_pipeline.py`
- `search(context)`: performs the search and returns a list of posting dictionaries.

Each posting must include `institution`, `title`, and `official_url`. Optional fields follow the canonical schema in `docs/mandatory-search-workflow.md`. Do not label a posting open or eligibility-verified unless the adapter has evidence supporting that status. Adapter failures and missing adapters are surfaced as limitations, never treated as zero results.

**Current limitation:** no source adapters are included yet. Running the command before adapters are installed should therefore return a blocked status; it must not be described as a completed job search.

See [mandatory execution and validation workflow](docs/mandatory-search-workflow.md).
