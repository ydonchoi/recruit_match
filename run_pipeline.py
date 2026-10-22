#!/usr/bin/env python3
"""Independent recruitment search and canonical analysis runner.

Search planning, query orchestration, evidence gates, and analysis stages are
implemented in this repository. Platform adapters and evidence-dependent
analysis services are explicit dependencies; missing services fail closed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOGS, DATA, REPORTS = ROOT / "logs", ROOT / "data", ROOT / "reports"
RUN_LOG = LOGS / "search_runs.jsonl"
POSTINGS_FILE = DATA / "postings.jsonl"
EVENTS_FILE = DATA / "posting_events.jsonl"
SUMMARY_FILE = REPORTS / "latest_run_summary.md"
ANALYSIS_FILE = DATA / "analysis_results.jsonl"
JOB_MATCH_FILE = DATA / "job_match_evaluations.jsonl"

BASELINE_PLATFORMS = [
    "JOB-ALIO", "NKIS", "나라일터", "고용24", "사람인", "잡코리아",
    "클린아이 잡플러스", "대학 공식 채용 페이지", "하이브레인넷",
    "연구기관 공식 채용 페이지", "KEDI", "KICE",
]
VALID_RUN_STATUS = {"completed", "partially_completed", "blocked"}
VALID_APPLICATION_STATUS = {"open", "closed", "unknown"}
VALID_ELIGIBILITY_STATUS = {"verified", "partially_verified", "unverified", "not_eligible"}
VALID_FIT = {"high", "review", "low", "unassessed"}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("JSONL row must be an object")
            rows.append(row)
        except Exception as exc:
            raise RuntimeError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def upsert_run_record(run: dict[str, Any]) -> None:
    """Keep one latest-state record per run_id; preserve other runs."""
    rows = read_jsonl(RUN_LOG)
    for i, old in enumerate(rows):
        if old.get("run_id") == run["run_id"]:
            rows[i] = run
            break
    else:
        rows.append(run)
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    temp = RUN_LOG.with_suffix(".jsonl.tmp")
    temp.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temp.replace(RUN_LOG)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temp.replace(path)


def load_adapters() -> dict[str, Any]:
    """Load adapters/*.py; modules may expose ADAPTERS or PLATFORM+search."""
    folder = ROOT / "adapters"
    adapters: dict[str, Any] = {}
    if not folder.is_dir():
        return adapters
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"recruit_adapter_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(spec.name, None)
            adapters[f"__LOAD_ERROR__:{path.stem}"] = exc
            continue
        provided = getattr(module, "ADAPTERS", None)
        if isinstance(provided, dict):
            for platform, adapter in provided.items():
                if callable(getattr(adapter, "search", None)):
                    adapters[str(platform)] = adapter
        elif getattr(module, "PLATFORM", None) and callable(getattr(module, "search", None)):
            adapters[str(module.PLATFORM)] = module

    # Compose the policy-bounded HTML crawler with the API discovery adapter
    # for configured baseline platforms. Missing/invalid crawl config is not
    # silently replaced with guessed seed URLs.
    try:
        from adapters.public_html_crawl import CompositeAdapter, build_crawl_adapters
        crawl_adapters = build_crawl_adapters()
        for platform, crawl_adapter in crawl_adapters.items():
            existing = adapters.get(platform)
            if existing is not None and not str(platform).startswith("__LOAD_ERROR__:"):
                adapters[platform] = CompositeAdapter(platform, (existing, crawl_adapter))
            else:
                adapters[platform] = crawl_adapter
    except Exception as exc:
        adapters["__LOAD_ERROR__:public_html_crawl"] = exc
    return adapters

def load_query_plan(user_query: str, axes: list[str], limit: int) -> list[str]:
    """Use the locally ported planner; no legacy repository path/import is allowed."""
    try:
        from search_engine import CandidateEvidence, SearchMatrixPlanner, AdaptiveSearchPlanner
    except Exception as exc:
        raise RuntimeError(f"Could not import local search engine: {type(exc).__name__}: {exc}") from exc
    planner = AdaptiveSearchPlanner(SearchMatrixPlanner(), outcome_memory={})
    evidence = CandidateEvidence(tuple(axes))
    plans = planner.plan(evidence, user_query, limit=limit)
    queries = []
    for plan in plans:
        query = str(plan.combination.query).strip()
        if query and query not in queries:
            queries.append(query)
    if not queries:
        raise RuntimeError("Local planner returned no executable queries")
    return queries

def normalize_posting(raw: dict[str, Any], run_id: str, checked_at: str) -> dict[str, Any]:
    required = ("institution", "title", "official_url")
    missing = [key for key in required if not str(raw.get(key, "")).strip()]
    if missing:
        raise ValueError(f"posting missing required fields: {', '.join(missing)}")
    url = str(raw["official_url"]).strip()
    application_status = raw.get("application_status", "unknown")
    eligibility_status = raw.get("eligibility_status", "unverified")
    fit = raw.get("fit_assessment", "unassessed")
    return {
        "posting_id": str(raw.get("posting_id") or url).strip(),
        "institution": str(raw["institution"]).strip(),
        "title": str(raw["title"]).strip(),
        "official_url": url,
        "alternate_source_urls": sorted(set(raw.get("alternate_source_urls", []))),
        "location": raw.get("location"),
        "employment_type": raw.get("employment_type") if raw.get("employment_type") in {"regular", "contract", "fixed_term", "other", "unknown"} else "unknown",
        "opened_at": raw.get("opened_at"),
        "deadline_at": raw.get("deadline_at"),
        "application_status": application_status if application_status in VALID_APPLICATION_STATUS else "unknown",
        "eligibility_status": eligibility_status if eligibility_status in VALID_ELIGIBILITY_STATUS else "unverified",
        "fit_assessment": fit if fit in VALID_FIT else "unassessed",
        "eligibility_evidence": list(raw.get("eligibility_evidence", [])),
        "authoritative_source": raw.get("authoritative_source") is True,
        "decision_source_verified": raw.get("decision_source_verified") is True,
        "evidence_refs": list(raw.get("evidence_refs", [])),
        "provenance_refs": list(raw.get("provenance_refs", [])),
        "candidate_recruitment_evidence_separated": raw.get("candidate_recruitment_evidence_separated") is True,
        "duplicate_conflict": raw.get("duplicate_conflict") is True,
        "job_fit_score": raw.get("job_fit_score") if isinstance(raw.get("job_fit_score"), (int, float)) else None,
        "official_compensation": raw.get("official_compensation"),
        "institution_compensation": raw.get("institution_compensation"),
        "public_benchmark_compensation": raw.get("public_benchmark_compensation"),
        "compensation_estimate": raw.get("compensation_estimate"),
        "source_platform": raw.get("source_platform"),
        "source_type": raw.get("source_type"),
        "source_content_sha256": raw.get("source_content_sha256"),
        "source_artifact": raw.get("source_artifact"),
        "detail_acquisition_status": raw.get("detail_acquisition_status", "NOT_ATTEMPTED"),
        "detail_acquisition_error": raw.get("detail_acquisition_error"),
        "acquired_source_url": raw.get("acquired_source_url"),
        "acquired_content_type": raw.get("acquired_content_type"),
        "acquired_content_sha256": raw.get("acquired_content_sha256"),
        "acquired_source_artifact": raw.get("acquired_source_artifact"),
        "source_discovery_errors": list(raw.get("source_discovery_errors", [])),
        "first_seen_run_id": raw.get("first_seen_run_id") or run_id,
        "last_checked_at": checked_at,
        "last_checked_run_id": run_id,
    }


def write_summary(run: dict[str, Any], ledger: list[dict[str, Any]]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    statuses = {s: sum(p.get("application_status") == s for p in ledger) for s in sorted(VALID_APPLICATION_STATUS)}
    eligible = sum(p.get("eligibility_status") == "verified" for p in ledger)
    lines = [
        "# Latest recruitment search run", "",
        f"- Run ID: `{run['run_id']}`",
        f"- Started: {run['started_at']}",
        f"- Ended: {run['ended_at']}",
        f"- Status: **{run['status']}**",
        f"- Local planner: {run['planner_status']}",
        f"- Analysis status: {run.get('analysis_status', 'NOT_RUN')}",
        f"- Platforms with successful adapter calls: {run['platforms_succeeded']}/{run['platforms_expected']}",
        f"- Raw results: {run['raw_result_count'] if run['raw_result_count'] is not None else 'unknown'}",
        f"- New postings: {run['new_postings']}",
        f"- Duplicates: {run['duplicates']}",
        f"- Updated postings: {run['updated_postings']}",
        f"- Unique cumulative postings: {len(ledger)}", "",
        "## Cumulative application status",
        f"- Open: {statuses['open']}",
        f"- Closed: {statuses['closed']}",
        f"- Unknown: {statuses['unknown']}",
        f"- Eligibility verified: {eligible}", "",
        "## Platform status",
    ]
    lines.extend(f"- {platform}: {status}" for platform, status in run["platform_statuses"].items())
    lines += ["", "## Errors and limitations"]
    lines.extend(f"- {item}" for item in run["errors_or_limitations"] or ["None recorded"])
    lines += ["", "A blocked platform is not evidence that no relevant postings exist.", ""]
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text("\n".join(lines), encoding="utf-8")


def run_pipeline(iteration: int, axes: list[str], user_query: str, query_limit: int, job_match_input: str | None = None) -> int:
    started = now()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    for folder in (LOGS, DATA, REPORTS):
        folder.mkdir(parents=True, exist_ok=True)

    run: dict[str, Any] = {
        "run_id": run_id, "started_at": started, "ended_at": None,
        "iteration": iteration, "platform": "multi-platform",
        "query_axes": axes, "queries_executed": [],
        "status": "blocked", "raw_result_count": None, "new_postings": 0,
        "duplicates": 0, "updated_postings": 0, "errors_or_limitations": [],
        "evidence_urls": [], "platforms_expected": len(BASELINE_PLATFORMS),
        "platforms_attempted": 0, "platforms_succeeded": 0,
        "platform_statuses": {}, "planner_status": "not_configured",
    }
    upsert_run_record(run)

    try:
        if not user_query.strip():
            raise ValueError("A non-empty --request is required")
        queries = load_query_plan(user_query, axes, query_limit)
        run["planner_status"] = "executed"
        run["queries_executed"] = queries

        adapters = load_adapters()
        ledger_rows = read_jsonl(POSTINGS_FILE)
        index = {str(p.get("official_url") or p.get("posting_id")): p for p in ledger_rows}
        from search_orchestrator import execute_search_plan, summarize_executions
        executions = execute_search_plan(
            run_id=run_id, queries=queries, platforms=BASELINE_PLATFORMS,
            adapters=adapters,
            context={"iteration": iteration, "query_axes": axes,
                     "user_query": user_query, "planner": "recruit_match.search_engine"},
        )
        run["orchestration_summary"] = summarize_executions(executions)
        raw_count = 0
        succeeded_platforms = set()
        attempted_platforms = set()
        platform_execution_statuses = {}
        for adapter_key, adapter_error in adapters.items():
            if adapter_key.startswith("__LOAD_ERROR__:"):
                run["errors_or_limitations"].append(f"Adapter module {adapter_key.split(chr(58), 1)[1]} failed to load: {type(adapter_error).__name__}: {adapter_error}")
        for execution in executions:
            platform = execution.run.platform
            attempted_platforms.add(platform)
            platform_execution_statuses.setdefault(platform, []).append(execution.run.status)
            if execution.run.status == "COMPLETED":
                succeeded_platforms.add(platform)
                raw_count += len(execution.hits)
            elif execution.run.status == "BLOCKED":
                run["errors_or_limitations"].append(f"{platform}: no installed adapter; query not executed")
            else:
                run["errors_or_limitations"].append(f"{platform} query failed: {execution.run.error}")
            for hit in execution.hits:
                for source_error in hit.raw.get("source_discovery_errors", []):
                    run["errors_or_limitations"].append(
                        f"{platform} partial discovery source failure: {source_error}"
                    )
                if hit.raw.get("detail_acquisition_status") == "FAILED":
                    run["errors_or_limitations"].append(
                        f"{platform} detail acquisition failed for {hit.raw.get('official_url')}: "
                        f"{hit.raw.get('detail_acquisition_error', 'UNKNOWN_ERROR')}"
                    )
                try:
                    posting = normalize_posting(hit.raw, run_id, hit.observed_at)
                    key = posting["official_url"]
                    append_jsonl(EVENTS_FILE, {
                        "event_id": uuid.uuid4().hex, "posting_id": posting["posting_id"],
                        "run_id": run_id, "event_type": "discovered",
                        "occurred_at": hit.observed_at, "evidence_urls": [posting["official_url"]],
                        "notes": f"Discovered by search orchestrator on {platform}; official status and eligibility remain unverified unless evidence says otherwise.",
                    })
                    if key in index:
                        old = index[key]
                        if old != posting:
                            merged = {**old, **posting}
                            merged["alternate_source_urls"] = sorted(set(old.get("alternate_source_urls", [])) | set(posting.get("alternate_source_urls", [])))
                            index[key] = merged
                            run["updated_postings"] += 1
                        else:
                            run["duplicates"] += 1
                    else:
                        index[key] = posting
                        run["new_postings"] += 1
                    run["evidence_urls"].append(posting["official_url"])
                except Exception as exc:
                    run["errors_or_limitations"].append(
                        f"Could not normalize hit from {platform} ({hit.hit_id}): {type(exc).__name__}: {exc}"
                    )
        run["platform_statuses"] = {}
        for platform in BASELINE_PLATFORMS:
            statuses = platform_execution_statuses.get(platform, [])
            if not statuses or all(status == "BLOCKED" for status in statuses):
                platform_status = "blocked"
            elif all(status == "COMPLETED" for status in statuses):
                platform_status = "completed"
            elif any(status == "COMPLETED" for status in statuses):
                platform_status = "partially_completed"
            else:
                platform_status = "failed"
            run["platform_statuses"][platform] = platform_status
        run["platforms_attempted"] = len(attempted_platforms)
        run["platforms_succeeded"] = len(succeeded_platforms)
        run["raw_result_count"] = raw_count if succeeded_platforms else None
        ledger = list(index.values())
        write_jsonl(POSTINGS_FILE, ledger)

        # Run the canonical analysis stages over the observed cumulative ledger.
        # External evidence-dependent services are explicit optional hooks; absent
        # hooks block the full pipeline rather than fabricate verification.
        from analysis_pipeline import run_analysis_pipeline
        analysis_services = {}
        service_path = ROOT / "analysis_services.py"
        if service_path.is_file():
            spec = importlib.util.spec_from_file_location("recruit_match_analysis_services", service_path)
            if spec is None or spec.loader is None:
                run["errors_or_limitations"].append("analysis_services.py exists but cannot be loaded")
            else:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                supplied = getattr(module, "SERVICES", {})
                if not isinstance(supplied, dict):
                    raise TypeError("analysis_services.py SERVICES must be a dict")
                analysis_services = supplied
        analysis = run_analysis_pipeline(
            run_id=run_id, postings=ledger, services=analysis_services,
            require_all_services=True, top_n=50,
        )
        write_jsonl(ANALYSIS_FILE, [dict(row) for row in analysis.records])

        # Optional requirement-centered candidate-material evaluation. Source
        # documents are read on demand; no normalized applicant profile is built.
        if job_match_input:
            match_path = Path(job_match_input).expanduser()
            if not match_path.is_absolute():
                match_path = ROOT / match_path
            payload = json.loads(match_path.read_text(encoding="utf-8"))
            from analysis_pipeline import evaluate_job_matching_payload
            match_result = evaluate_job_matching_payload(payload)
            append_jsonl(JOB_MATCH_FILE, match_result)
            run["job_matching_status"] = match_result.get("evaluation_status", "UNASSESSED")
            run["job_matching_evaluation_id"] = match_result.get("evaluation_id")
            run["job_matching_output"] = str(JOB_MATCH_FILE.relative_to(ROOT))
            if match_result.get("evaluation_status") in {"UNASSESSED", "PROVISIONAL"}:
                run["errors_or_limitations"].append(
                    f"Job matching evaluation is {match_result.get('evaluation_status')}; review unresolved requirements and evidence."
                )
        else:
            run["job_matching_status"] = "NOT_REQUESTED"

        run["analysis_status"] = analysis.status
        run["analysis_stages"] = [asdict(stage) for stage in analysis.stages]
        run["analysis_errors"] = list(analysis.errors)
        if analysis.status != "COMPLETED":
            run["errors_or_limitations"].append(
                f"Canonical analysis pipeline status: {analysis.status}"
            )
            run["errors_or_limitations"].extend(analysis.errors)

        # Completion requires every required query/platform pair to execute,
        # no recorded collection/normalization/adapter limitation, successful
        # analysis stages in canonical order, and all required output artifacts.
        expected_pairs = len(queries) * len(BASELINE_PLATFORMS)
        orchestration = run.get("orchestration_summary", {})
        actual_pairs = orchestration.get("queries_platform_pairs", 0)
        completed_pairs = orchestration.get("completed", 0)
        failed_pairs = orchestration.get("failed", 0)
        blocked_pairs = orchestration.get("blocked", 0)
        required_stage_names = (
            "discovery", "opportunity_state_resolution", "assessment_resolution",
            "evidence_validation", "eligibility", "assessment", "compensation",
            "ranking", "top50", "writer_gate", "revalidation",
        )
        stage_names = [stage.get("name") for stage in run.get("analysis_stages", [])]
        stage_statuses = [stage.get("status") for stage in run.get("analysis_stages", [])]
        all_stages_present = stage_names == list(required_stage_names)
        all_stages_completed = all(status == "COMPLETED" for status in stage_statuses)
        artifacts_written = all(path.is_file() for path in (RUN_LOG, POSTINGS_FILE, EVENTS_FILE, ANALYSIS_FILE))
        no_limitations = not run["errors_or_limitations"]
        full_search_coverage = (
            expected_pairs > 0
            and actual_pairs == expected_pairs
            and completed_pairs == expected_pairs
            and failed_pairs == 0
            and blocked_pairs == 0
        )
        full_analysis = analysis.status == "COMPLETED" and all_stages_present and all_stages_completed
        if full_search_coverage and no_limitations and full_analysis and artifacts_written:
            run["status"] = "completed"
        elif completed_pairs > 0 or analysis.status in {"COMPLETED", "PARTIALLY_COMPLETED"}:
            run["status"] = "partially_completed"
        else:
            run["status"] = "blocked"

        # Persist the terminal run state before creating the human-readable
        # summary; a failed artifact write must never yield a success exit code.
        run["ended_at"] = now()
        upsert_run_record(run)
        write_summary(run, ledger)
        artifacts_written = all(path.is_file() for path in (RUN_LOG, POSTINGS_FILE, EVENTS_FILE, ANALYSIS_FILE, SUMMARY_FILE))
        print(json.dumps({
            "run_id": run_id, "status": run["status"],
            "planner_status": run["planner_status"],
            "analysis_status": run.get("analysis_status", "NOT_RUN"),
            "job_matching_status": run.get("job_matching_status", "NOT_REQUESTED"),
            "job_matching_output": run.get("job_matching_output"),
            "analysis_stages": run.get("analysis_stages", []),
            "analysis_errors": run.get("analysis_errors", []),
            "platforms_expected": run["platforms_expected"],
            "platforms_succeeded": len(succeeded_platforms), "platform_statuses": run["platform_statuses"],
            "raw_result_count": run["raw_result_count"], "new_postings": run["new_postings"],
            "duplicates": run["duplicates"], "updated_postings": run["updated_postings"],
            "errors_or_limitations": run["errors_or_limitations"],
            "summary": str(SUMMARY_FILE.relative_to(ROOT)),
        }, ensure_ascii=False, indent=2))
        return 0 if run["status"] == "completed" else 2
    except Exception as exc:
        run["ended_at"] = now()
        run["status"] = "blocked"
        run["errors_or_limitations"].append(f"Pipeline gate: {type(exc).__name__}: {exc}")
        upsert_run_record(run)
        print(f"PIPELINE BLOCKED: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent recruitment search pipeline.")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--axis", action="append", dest="axes", default=[], help="Search axis; repeat as needed.")
    parser.add_argument("--request", required=True, help="User's recruitment-search request.")
    parser.add_argument("--query-limit", type=int, default=120, help="Maximum planned queries per run (default: 120).")
    parser.add_argument("--job-match-input", help="Optional JSON input with job requirements, source documents, and criterion decisions; no applicant profile is created.")
    args = parser.parse_args()
    if args.iteration < 1:
        parser.error("--iteration must be >= 1")
    if not args.axes:
        args.axes = ["대학", "공공기관", "연구기관", "교육기관", "교육기업"]
    if args.query_limit < 1:
        parser.error("--query-limit must be >= 1")
    return run_pipeline(args.iteration, args.axes, args.request, args.query_limit, args.job_match_input)


if __name__ == "__main__":
    raise SystemExit(main())
