#!/usr/bin/env python3
"""Mandatory recruitment-search pipeline gate.

This runner records only work actually performed by installed source adapters.
Without adapters, platforms are recorded as blocked and the run cannot be completed.
Python 3.10+, standard library only.
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
LOGS = ROOT / "logs"
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
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
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("JSONL row must be an object")
            rows.append(value)
        except Exception as exc:
            raise RuntimeError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temp.replace(path)


def load_adapters() -> list[Any]:
    """Load adapters/*.py exposing PLATFORM and search(context)->list[posting dict]."""
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


def normalize_posting(raw: dict[str, Any], run_id: str, checked_at: str) -> dict[str, Any]:
    required = ("institution", "title", "official_url")
    missing = [key for key in required if not str(raw.get(key, "")).strip()]
    if missing:
        raise ValueError(f"posting missing required fields: {', '.join(missing)}")
    url = str(raw["official_url"]).strip()
    posting_id = str(raw.get("posting_id") or url).strip()
    employment_type = raw.get("employment_type", "unknown")
    if employment_type not in {"regular", "contract", "fixed_term", "other", "unknown"}:
        employment_type = "unknown"
    application_status = raw.get("application_status", "unknown")
    if application_status not in VALID_APPLICATION_STATUS:
        application_status = "unknown"
    eligibility_status = raw.get("eligibility_status", "unverified")
    if eligibility_status not in VALID_ELIGIBILITY_STATUS:
        eligibility_status = "unverified"
    fit = raw.get("fit_assessment", "unassessed")
    if fit not in VALID_FIT:
        fit = "unassessed"
    return {
        "posting_id": posting_id,
        "institution": str(raw["institution"]).strip(),
        "title": str(raw["title"]).strip(),
        "official_url": url,
        "alternate_source_urls": sorted(set(raw.get("alternate_source_urls", []))),
        "location": raw.get("location"),
        "employment_type": employment_type,
        "opened_at": raw.get("opened_at"),
        "deadline_at": raw.get("deadline_at"),
        "application_status": application_status,
        "eligibility_status": eligibility_status,
        "fit_assessment": fit,
        "eligibility_evidence": list(raw.get("eligibility_evidence", [])),
        "first_seen_run_id": raw.get("first_seen_run_id") or run_id,
        "last_checked_at": checked_at,
        "last_checked_run_id": run_id,
    }


def write_summary(run: dict[str, Any], ledger: list[dict[str, Any]]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    statuses = {s: sum(1 for p in ledger if p.get("application_status") == s)
                for s in sorted(VALID_APPLICATION_STATUS)}
    eligible = sum(1 for p in ledger if p.get("eligibility_status") == "verified")
    text = [
        "# Latest recruitment search run", "",
        f"- Run ID: `{run['run_id']}`",
        f"- Started: {run['started_at']}",
        f"- Ended: {run['ended_at']}",
        f"- Run status: **{run['status']}**",
        f"- Platform results recorded: {run['platforms_attempted']}/{run['platforms_expected']}",
        f"- Raw result count: {run['raw_result_count'] if run['raw_result_count'] is not None else 'unknown'}",
        f"- New postings: {run['new_postings']}",
        f"- Duplicate postings: {run['duplicates']}",
        f"- Updated postings: {run['updated_postings']}",
        f"- Errors/limitations: {len(run['errors_or_limitations'])}", "",
        "## Cumulative ledger",
        f"- Unique postings: {len(ledger)}",
        f"- Open: {statuses['open']}",
        f"- Closed: {statuses['closed']}",
        f"- Status unknown: {statuses['unknown']}",
        f"- Eligibility verified: {eligible}", "",
        "## Limitations",
    ]
    text.extend([f"- {item}" for item in run["errors_or_limitations"]] or ["- None recorded"])
    text += ["", "This report is generated from persisted run and posting records. A blocked platform is not evidence that no postings exist.", ""]
    SUMMARY_FILE.write_text("\n".join(text), encoding="utf-8")


def run_pipeline(iteration: int, query_axes: list[str], queries: list[str]) -> int:
    started = now()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    LOGS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    # Persist a run-start record before any source adapter is invoked.
    run = {
        "run_id": run_id, "started_at": started, "ended_at": None,
        "iteration": iteration, "platform": "multi-platform",
        "query_axes": query_axes, "queries_executed": [],
        "status": "blocked", "raw_result_count": None, "new_postings": 0,
        "duplicates": 0, "updated_postings": 0, "errors_or_limitations": [],
        "evidence_urls": [], "platforms_expected": len(BASELINE_PLATFORMS),
        "platforms_attempted": 0, "platform_statuses": {},
    }
    upsert_run_record(run)

    try:
        if not queries:
            raise ValueError("At least one exact query is required; refusing to mark a run complete.")
        adapters = load_adapters()
        adapter_by_platform = {str(a.PLATFORM): a for a in adapters}
        ledger_rows = read_jsonl(POSTINGS_FILE)
        # Use URL as a stable dedupe key, with posting_id as fallback.
        index = {str(p.get("official_url") or p.get("posting_id")): p for p in ledger_rows}
        raw_count = 0
        platform_successes = 0
        total_attempted = 0

        for platform in BASELINE_PLATFORMS:
            adapter = adapter_by_platform.get(platform)
            if adapter is None:
                run["platform_statuses"][platform] = "blocked"
                run["errors_or_limitations"].append(f"{platform}: no installed adapter; search not executed.")
                continue
            total_attempted += 1
            try:
                run["queries_executed"] = sorted(set(run["queries_executed"]) | set(queries))
                found = adapter.search({
                    "run_id": run_id, "iteration": iteration,
                    "query_axes": query_axes, "queries": queries,
                    "platform": platform,
                })
                if not isinstance(found, list):
                    raise TypeError("adapter search() must return a list")
                platform_successes += 1
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
                        "notes": "Adapter-returned record; official-source verification depends on supplied evidence.",
                    })
                    if key in index:
                        old = index[key]
                        if old != posting:
                            merged = {**old, **posting}
                            alternates = set(old.get("alternate_source_urls", [])) | set(posting.get("alternate_source_urls", []))
                            merged["alternate_source_urls"] = sorted(alternates)
                            index[key] = merged
                            run["updated_postings"] += 1
                        else:
                            run["duplicates"] += 1
                    else:
                        index[key] = posting
                        run["new_postings"] += 1
            except Exception as exc:
                run["platform_statuses"][platform] = "failed"
                run["errors_or_limitations"].append(f"{platform}: adapter failed: {type(exc).__name__}: {exc}")

        run["platforms_attempted"] = total_attempted
        run["raw_result_count"] = raw_count if platform_successes else None
        ledger = list(index.values())
        write_jsonl(POSTINGS_FILE, ledger)
        if platform_successes == len(BASELINE_PLATFORMS) and not run["errors_or_limitations"]:
            run["status"] = "completed"
        elif platform_successes:
            run["status"] = "partially_completed"
        else:
            run["status"] = "blocked"
        run["ended_at"] = now()
        # Append final state only after result ledger and events are written.
        upsert_run_record(run)
        write_summary(run, ledger)
        print(json.dumps({
            "run_id": run_id, "status": run["status"],
            "platforms_expected": run["platforms_expected"],
            "platforms_with_adapters_attempted": total_attempted,
            "platform_statuses": run["platform_statuses"],
            "new_postings": run["new_postings"], "duplicates": run["duplicates"],
            "updated_postings": run["updated_postings"],
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
    parser = argparse.ArgumentParser(description="Run the mandatory recruitment search pipeline.")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--axis", action="append", dest="axes", default=[], help="Search axis; repeat as needed.")
    parser.add_argument("--query", action="append", default=[], help="Exact query actually sent to adapters; repeat as needed.")
    args = parser.parse_args()
    if args.iteration < 1:
        parser.error("--iteration must be >= 1")
    if not args.axes:
        args.axes = ["job title", "institution type", "region", "employment type"]
    return run_pipeline(args.iteration, args.axes, args.query)


if __name__ == "__main__":
    raise SystemExit(main())
