"""Independent search orchestration port for recruit_match.

Implements bounded multi-query execution, per-query lineage, error isolation,
deduplication, and explicit execution evidence. Platform/network behavior remains
provided by adapters; this module never fabricates search results.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
import hashlib


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SearchRun:
    run_id: str
    query_id: str
    query: str
    platform: str
    started_at: str
    ended_at: str | None = None
    status: str = "PENDING"
    result_count: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class SearchHit:
    hit_id: str
    run_id: str
    platform: str
    query: str
    raw: dict[str, Any]
    observed_at: str


@dataclass(frozen=True)
class QueryExecution:
    run: SearchRun
    hits: tuple[SearchHit, ...]


def stable_query_id(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def execute_search_plan(*, run_id: str, queries: Iterable[str], platforms: Iterable[str],
                        adapters: dict[str, Any], context: dict[str, Any]) -> tuple[QueryExecution, ...]:
    """Execute every unique query against each configured platform adapter."""
    executions: list[QueryExecution] = []
    seen_queries: set[str] = set()
    for query in queries:
        query = str(query).strip()
        if not query or query in seen_queries:
            continue
        seen_queries.add(query)
        for platform in platforms:
            adapter = adapters.get(platform)
            started = utc_now()
            query_run_id = f"{run_id}:{stable_query_id(query)}:{stable_query_id(platform)}"
            if adapter is None:
                executions.append(QueryExecution(
                    SearchRun(query_run_id, stable_query_id(query), query, platform, started,
                              utc_now(), "BLOCKED", None, "NO_ADAPTER"),
                    (),
                ))
                continue
            try:
                result = adapter.search({**context, "run_id": query_run_id, "query": query, "queries": [query], "platform": platform})
                if not isinstance(result, list):
                    raise TypeError("adapter.search must return list[dict]")
                hits = []
                for item in result:
                    if not isinstance(item, dict):
                        raise TypeError("search result must be dict")
                    raw_identity = str(item.get("official_url") or item.get("posting_id") or repr(sorted(item.items())))
                    hit_id = hashlib.sha256(f"{platform}|{raw_identity}".encode()).hexdigest()[:20]
                    hits.append(SearchHit(hit_id, query_run_id, platform, query, item, utc_now()))
                executions.append(QueryExecution(
                    SearchRun(query_run_id, stable_query_id(query), query, platform, started,
                              utc_now(), "COMPLETED", len(hits), None),
                    tuple(hits),
                ))
            except Exception as exc:
                executions.append(QueryExecution(
                    SearchRun(query_run_id, stable_query_id(query), query, platform, started,
                              utc_now(), "FAILED", None, f"{type(exc).__name__}: {exc}"),
                    (),
                ))
    return tuple(executions)


def summarize_executions(executions: Iterable[QueryExecution]) -> dict[str, Any]:
    rows = tuple(executions)
    return {
        "queries_platform_pairs": len(rows),
        "completed": sum(row.run.status == "COMPLETED" for row in rows),
        "failed": sum(row.run.status == "FAILED" for row in rows),
        "blocked": sum(row.run.status == "BLOCKED" for row in rows),
        "raw_results": sum(len(row.hits) for row in rows),
        "execution_records": [asdict(row.run) for row in rows],
    }
