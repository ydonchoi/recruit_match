#!/usr/bin/env python3
"""Independent recruitment search and canonical analysis runner.

Search planning, query orchestration, evidence gates, and analysis stages are
implemented in this repository. Platform adapters and evidence-dependent
analysis services are explicit dependencies; missing services fail closed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
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
    rows = [sanitize_run_record(old, legacy=True) for old in rows]
    run = sanitize_run_record(run)
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


def sanitize_run_record(run: dict[str, Any], *, legacy: bool = False) -> dict[str, Any]:
    """Remove search text and candidate-specific fields before persistence."""
    allowed = {
        "run_id", "started_at", "ended_at", "iteration", "platform",
        "query_count", "query_refs", "status", "raw_result_count", "new_postings",
        "duplicates", "updated_postings", "errors_or_limitations", "evidence_urls",
        "platforms_expected", "platforms_attempted", "platforms_succeeded",
        "platform_statuses", "planner_status", "orchestration_summary", "analysis_status",
    }
    sensitive_keys = {
        "query_axes", "queries_executed", "user_query", "candidate_text",
        "candidate_profile", "applicant_profile", "job_matching_output",
        "job_matching_evaluation_id", "job_match_input", "job_matching_status",
        "documents", "decisions", "fit_score", "criterion_results", "evidence_records",
    }
    had_legacy_text = any(key in run for key in sensitive_keys)
    safe = {key: value for key, value in run.items() if key in allowed}
    summary = safe.get("orchestration_summary")
    if isinstance(summary, dict):
        summary = dict(summary)
        records = summary.get("execution_records", [])
        clean_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if "query" in record:
                had_legacy_text = True
            clean_record = {
                key: record.get(key)
                for key in ("run_id", "query_id", "platform", "started_at", "ended_at",
                            "status", "result_count", "error", "execution_mode")
                if key in record
            }
            if clean_record.get("error"):
                clean_record["error"] = str(clean_record["error"]).split(":", 1)[0]
            clean_records.append(clean_record)
        summary["execution_records"] = clean_records
        safe["orchestration_summary"] = summary
    errors = safe.get("errors_or_limitations")
    if isinstance(errors, list):
        safe["errors_or_limitations"] = [safe_error_label(value) for value in errors]
    if legacy and had_legacy_text:
        safe["errors_or_limitations"] = ["LEGACY_DETAILS_REDACTED"]
        safe["query_refs"] = []
        if isinstance(safe.get("orchestration_summary"), dict):
            safe["orchestration_summary"]["execution_records"] = []
    return safe


def sanitize_search_text(value: str) -> str:
    """Remove common direct identifiers before user text reaches search APIs."""
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", " ", value)
    text = re.sub(r"(?<!\d)(?:\+?82[- .]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)", " ", text)
    text = re.sub(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def safe_error_label(value: Any) -> str:
    """Map diagnostics to fixed labels so exception text cannot persist."""
    message = str(value)
    known = {
        "LEGACY_DETAILS_REDACTED", "PIPELINE_GATE_FAILURE", "NORMALIZATION_FAILURE",
        "ADAPTER_LOAD_FAILURE", "NO_ADAPTER", "QUERY_FAILED",
        "PARTIAL_DISCOVERY_FAILURE", "DETAIL_ACQUISITION_FAILURE",
        "OPERATIONAL_LIMITATION",
    }
    if message in known or re.fullmatch(r"[A-Z0-9-]+: (NO_ADAPTER|QUERY_FAILED|PARTIAL_DISCOVERY_FAILURE|DETAIL_ACQUISITION_FAILURE)", message):
        return message
    prefix = message.split(":", 1)[0]
    platform = prefix if prefix in BASELINE_PLATFORMS else ""
    if "no installed adapter" in message:
        return f"{platform}: NO_ADAPTER" if platform else "NO_ADAPTER"
    if "query failed" in message:
        return f"{platform}: QUERY_FAILED" if platform else "QUERY_FAILED"
    if "partial discovery source failure" in message:
        return f"{platform}: PARTIAL_DISCOVERY_FAILURE" if platform else "PARTIAL_DISCOVERY_FAILURE"
    if "detail acquisition failed" in message:
        return f"{platform}: DETAIL_ACQUISITION_FAILURE" if platform else "DETAIL_ACQUISITION_FAILURE"
    if message.startswith("Could not normalize hit"):
        return "NORMALIZATION_FAILURE"
    if message.startswith("Adapter module"):
        return "ADAPTER_LOAD_FAILURE"
    if message.startswith("Pipeline gate"):
        return "PIPELINE_GATE_FAILURE"
    return "OPERATIONAL_LIMITATION"


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
        # HTML discovery is optional when the policy-reviewed config is absent;
        # the public-search API still covers those platform pairs.
        if not (type(exc).__name__ == "CrawlConfigurationError"
                and str(exc) == "NO_TERMS_REVIEWED_CRAWL_CONFIGS: set RECRUIT_MATCH_CRAWL_CONFIG_JSON with reviewed seed URLs and host allowlists"):
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
        "source_discovery_errors": [safe_error_label(value) for value in raw.get("source_discovery_errors", [])],
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
        f"- Analysis status: {run.get('analysis_status', 'NOT_RUN_STAGE_1')}",
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


def load_analysis_services() -> dict[str, Any]:
    """Load public-posting analysis hooks without exposing exception payloads."""
    service_path = ROOT / "analysis_services.py"
    if not service_path.is_file():
        return {}
    spec = importlib.util.spec_from_file_location("recruit_match_analysis_services", service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ANALYSIS_SERVICES_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    supplied = getattr(module, "SERVICES", {})
    if not isinstance(supplied, dict):
        raise TypeError("ANALYSIS_SERVICES_MUST_BE_DICT")
    return supplied


def run_selected_analysis(posting_ids: list[str]) -> dict[str, Any]:
    """Run stage 2 only for explicitly selected public posting IDs."""
    requested = list(dict.fromkeys(str(value).strip() for value in posting_ids if str(value).strip()))
    if not requested:
        raise ValueError("SELECT_AT_LEAST_ONE_POSTING")
    ledger = read_jsonl(POSTINGS_FILE)
    by_id = {str(row.get("posting_id") or row.get("official_url")): row for row in ledger}
    missing = [posting_id for posting_id in requested if posting_id not in by_id]
    if missing:
        raise ValueError("UNKNOWN_POSTING_ID")
    selected = [by_id[posting_id] for posting_id in requested]
    from analysis_pipeline import run_analysis_pipeline
    run_id = "analysis-" + uuid.uuid4().hex[:12]
    try:
        result = run_analysis_pipeline(
            run_id=run_id, postings=selected,
            services=load_analysis_services(), require_all_services=True, top_n=len(selected),
        )
    except Exception as exc:
        return {
            "run_id": run_id, "status": "BLOCKED", "selected_count": len(selected),
            "records": [], "errors": [type(exc).__name__],
        }
    write_jsonl(ANALYSIS_FILE, [dict(row) for row in result.records])
    return {
        "run_id": run_id,
        "status": result.status,
        "selected_count": len(selected),
        "records": [dict(row) for row in result.records],
        "errors": [error.split(":", 1)[0] for error in result.errors],
    }


def run_pipeline(iteration: int, axes: list[str], user_query: str, query_limit: int) -> int:
    started = now()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    for folder in (LOGS, DATA, REPORTS):
        folder.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.touch(exist_ok=True)

    run: dict[str, Any] = {
        "run_id": run_id, "started_at": started, "ended_at": None,
        "iteration": iteration, "platform": "multi-platform",
        "query_count": 0, "query_refs": [],
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
        safe_query = sanitize_search_text(user_query)
        safe_axes = [sanitize_search_text(axis) for axis in axes]
        safe_axes = [axis for axis in safe_axes if axis]
        if not safe_query and not safe_axes:
            raise ValueError("NO_SEARCH_TERMS_AFTER_REDACTION")
        queries = load_query_plan(safe_query, safe_axes, query_limit)
        run["planner_status"] = "executed"
        run["query_count"] = len(queries)

        adapters = load_adapters()
        ledger_rows = read_jsonl(POSTINGS_FILE)
        index = {str(p.get("official_url") or p.get("posting_id")): p for p in ledger_rows}
        from search_orchestrator import execute_search_plan, summarize_executions
        executions = execute_search_plan(
            run_id=run_id, queries=queries, platforms=BASELINE_PLATFORMS,
            adapters=adapters,
            context={"iteration": iteration, "query_axes": safe_axes,
                     "user_query": safe_query, "planner": "recruit_match.search_engine"},
        )
        run["orchestration_summary"] = summarize_executions(executions)
        run["query_refs"] = list(dict.fromkeys(
            row["query_id"] for row in run["orchestration_summary"].get("execution_records", [])
        ))
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
                run["errors_or_limitations"].append(f"{platform} query failed: {str(execution.run.error or 'PROVIDER_ERROR').split(':', 1)[0]}")
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
                        f"Could not normalize hit from {platform} ({hit.hit_id}): {type(exc).__name__}"
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
        run["analysis_status"] = "NOT_RUN_STAGE_1"

        # Stage 1 completion covers collection only. Selected-job analysis is a
        # separate stage and does not block the search results list.
        expected_pairs = len(queries) * len(BASELINE_PLATFORMS)
        orchestration = run.get("orchestration_summary", {})
        actual_pairs = orchestration.get("queries_platform_pairs", 0)
        completed_pairs = orchestration.get("completed", 0)
        failed_pairs = orchestration.get("failed", 0)
        blocked_pairs = orchestration.get("blocked", 0)
        artifacts_written = all(path.is_file() for path in (RUN_LOG, POSTINGS_FILE, EVENTS_FILE))
        no_limitations = not run["errors_or_limitations"]
        full_search_coverage = (
            expected_pairs > 0
            and actual_pairs == expected_pairs
            and completed_pairs == expected_pairs
            and failed_pairs == 0
            and blocked_pairs == 0
        )
        if full_search_coverage and no_limitations and artifacts_written:
            run["status"] = "completed"
        elif completed_pairs > 0:
            run["status"] = "partially_completed"
        else:
            run["status"] = "blocked"

        # Persist the terminal run state before creating the human-readable
        # summary; a failed artifact write must never yield a success exit code.
        run["ended_at"] = now()
        run = sanitize_run_record(run)
        upsert_run_record(run)
        write_summary(run, ledger)
        artifacts_written = all(path.is_file() for path in (RUN_LOG, POSTINGS_FILE, EVENTS_FILE, SUMMARY_FILE))
        print(json.dumps({
            "run_id": run_id, "status": run["status"],
            "planner_status": run["planner_status"],
            "analysis_status": run.get("analysis_status", "NOT_RUN_STAGE_1"),
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
        run["errors_or_limitations"].append(f"Pipeline gate: {type(exc).__name__}")
        run = sanitize_run_record(run)
        upsert_run_record(run)
        print(f"PIPELINE BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent recruitment search pipeline.")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--axis", action="append", dest="axes", default=[], help="Search axis; repeat as needed.")
    parser.add_argument("--request", help="Recruitment-search request. Use --interactive-session to enter it without shell history.")
    parser.add_argument("--query-limit", type=int, default=120, help="Maximum planned queries per run (default: 120).")
    parser.add_argument("--analyze-posting", nargs="+", help="Run stage 2 for selected posting IDs only.")
    parser.add_argument("--interactive-session", action="store_true", help="Run the 3-stage workflow with personal inputs kept in memory only.")
    args = parser.parse_args()
    if args.iteration < 1:
        parser.error("--iteration must be >= 1")
    if not args.axes:
        args.axes = ["대학", "공공기관", "연구기관", "교육기관", "교육기업"]
    if args.query_limit < 1:
        parser.error("--query-limit must be >= 1")
    if args.analyze_posting:
        try:
            result = run_selected_analysis(args.analyze_posting)
        except Exception as exc:
            print(json.dumps({"status": "blocked", "error": type(exc).__name__}, ensure_ascii=False))
            return 2
        print(json.dumps({key: value for key, value in result.items() if key != "records"} |
                         {"records": result["records"]}, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "COMPLETED" else 2
    if args.interactive_session:
        from interactive_workflow import run_interactive_session
        return run_interactive_session(run_pipeline, run_selected_analysis)
    if not args.request:
        parser.error("--request is required unless --interactive-session or --analyze-posting is used")
    if not args.axes:
        args.axes = ["대학", "공공기관", "연구기관", "교육기관", "교육기업"]
    return run_pipeline(args.iteration, args.axes, args.request, args.query_limit)


if __name__ == "__main__":
    raise SystemExit(main())
