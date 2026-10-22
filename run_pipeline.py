#!/usr/bin/env python3
"""Integrated recruitment search runner.

Integrates the legacy recruitment_matching Search Agent's query-planning layer
with this repository's adapter execution, cumulative posting ledger, event log,
and completion gate. It never simulates live search results.

Python 3.10+, standard library only for the runner itself.
Legacy planner integration is enabled with --legacy-root pointing to a checkout
of ydonchoi/recruitment_matching. Platform adapters remain explicit dependencies.
"""
from __future__ import annotations

import argparse
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


def load_adapters() -> list[Any]:
    """Load adapters/*.py modules exposing PLATFORM and search(context)->list[dict]."""
    folder = ROOT / "adapters"
    adapters = []
    if not folder.is_dir():
        return adapters
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"recruit_adapter_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if getattr(module, "PLATFORM", None) and callable(getattr(module, "search", None)):
            adapters.append(module)
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


def run_pipeline(iteration: int, axes: list[str], user_query: str, query_limit: int) -> int:
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

        adapters = {str(a.PLATFORM): a for a in load_adapters()}
        ledger_rows = read_jsonl(POSTINGS_FILE)
        index = {str(p.get("official_url") or p.get("posting_id")): p for p in ledger_rows}
        raw_count = 0
        succeeded = 0
        attempted = 0

        for platform in BASELINE_PLATFORMS:
            adapter = adapters.get(platform)
            if adapter is None:
                run["platform_statuses"][platform] = "blocked"
                run["errors_or_limitations"].append(f"{platform}: no installed adapter; not searched")
                continue
            attempted += 1
            try:
                found = adapter.search({
                    "run_id": run_id, "iteration": iteration,
                    "query_axes": axes, "queries": queries,
                    "user_query": user_query, "platform": platform,
                    "planner": "recruit_match.search_engine",
                })
                if not isinstance(found, list):
                    raise TypeError("adapter search(context) must return a list")
                succeeded += 1
                run["platform_statuses"][platform] = "completed"
                raw_count += len(found)
                for raw in found:
                    if not isinstance(raw, dict):
                        raise TypeError("adapter result must be an object")
                    posting = normalize_posting(raw, run_id, now())
                    key = posting["official_url"]
                    append_jsonl(EVENTS_FILE, {
                        "event_id": uuid.uuid4().hex, "posting_id": posting["posting_id"],
                        "run_id": run_id, "event_type": "discovered_or_verified",
                        "occurred_at": now(), "evidence_urls": [posting["official_url"]],
                        "notes": "Adapter-returned result; official status/eligibility only as verified by its supplied evidence.",
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
                run["platform_statuses"][platform] = "failed"
                run["errors_or_limitations"].append(f"{platform}: {type(exc).__name__}: {exc}")

        run["platforms_attempted"] = attempted
        run["platforms_succeeded"] = succeeded
        run["raw_result_count"] = raw_count if succeeded else None
        ledger = list(index.values())
        write_jsonl(POSTINGS_FILE, ledger)

        if succeeded == len(BASELINE_PLATFORMS) and not run["errors_or_limitations"]:
            run["status"] = "completed"
        elif succeeded:
            run["status"] = "partially_completed"
        else:
            run["status"] = "blocked"
        run["ended_at"] = now()
        upsert_run_record(run)
        write_summary(run, ledger)
        print(json.dumps({
            "run_id": run_id, "status": run["status"],
            "planner_status": run["planner_status"],
            "platforms_expected": run["platforms_expected"],
            "platforms_succeeded": succeeded, "platform_statuses": run["platform_statuses"],
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
    parser = argparse.ArgumentParser(description="Integrated legacy recruitment search pipeline.")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--axis", action="append", dest="axes", default=[], help="Search axis; repeat as needed.")
    parser.add_argument("--request", required=True, help="User's recruitment-search request.")
    parser.add_argument("--query-limit", type=int, default=120, help="Maximum planned queries per run (default: 120).")
    args = parser.parse_args()
    if args.iteration < 1:
        parser.error("--iteration must be >= 1")
    if not args.axes:
        args.axes = ["대학", "공공기관", "연구기관", "교육기관", "교육기업"]
    if args.query_limit < 1:
        parser.error("--query-limit must be >= 1")
    return run_pipeline(args.iteration, args.axes, args.request, args.query_limit)


if __name__ == "__main__":
    raise SystemExit(main())
