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
import uuid


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
    execution_mode: str = "individual"


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
    """Return a query fingerprint for transient in-process deduplication only."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _components(adapter: Any) -> tuple[Any, ...]:
    """Expose composite adapter parts so batchable search can be shared."""
    parts = getattr(adapter, "adapters", None)
    return tuple(parts) if isinstance(parts, (tuple, list)) else (adapter,)


def execute_search_plan(*, run_id: str, queries: Iterable[str], platforms: Iterable[str],
                        adapters: dict[str, Any], context: dict[str, Any]) -> tuple[QueryExecution, ...]:
    """Execute every query/platform pair, batching shared providers when possible."""
    executions: list[QueryExecution] = []
    seen_queries: set[str] = set()
    platform_list = tuple(platforms)
    for query in queries:
        query = str(query).strip()
        if not query or query in seen_queries:
            continue
        seen_queries.add(query)
        query_started = utc_now()
        query_ref = uuid.uuid4().hex[:16]
        parts_by_platform = {
            platform: _components(adapters[platform]) if adapters.get(platform) is not None else ()
            for platform in platform_list
        }
        # Batch components of the same adapter type across channels. The public
        # search adapter uses this to fetch a combined domain set once and route
        # the returned links back to every matching platform.
        batch_groups: dict[type, dict[str, Any]] = {}
        for platform, parts in parts_by_platform.items():
            batch_parts = [part for part in parts if callable(getattr(part, "search_batch", None))]
            if batch_parts:
                batch_groups.setdefault(type(batch_parts[0]), {})[platform] = batch_parts[0]

        component_results: dict[str, list[tuple[list[dict[str, Any]], str | None]]] = {
            platform: [] for platform in platform_list
        }
        modes: dict[str, set[str]] = {platform: set() for platform in platform_list}
        for group in batch_groups.values():
            first = next(iter(group.values()))
            batch_context = {**context, "query": query, "queries": [query], "platforms": list(group)}
            try:
                grouped = first.search_batch(batch_context, group)
                if not isinstance(grouped, dict):
                    raise TypeError("search_batch must return a platform-to-results dict")
                for platform, part in group.items():
                    rows = grouped.get(platform, [])
                    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
                        raise TypeError("search_batch results must be lists of dicts")
                    component_results[platform].append((rows, None))
                    modes[platform].add("grouped")
            except Exception as batch_exc:
                # A batch failure must not silently skip channels: fall back to
                # each platform adapter and retain the fallback evidence.
                for platform, part in group.items():
                    platform_context = {**context, "query": query, "queries": [query], "platform": platform}
                    try:
                        rows = part.search(platform_context)
                        if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
                            raise TypeError("adapter.search must return list[dict]")
                        component_results[platform].append((rows, None))
                        modes[platform].add("individual_fallback")
                    except Exception as exc:
                        component_results[platform].append(([], f"{type(exc).__name__}"))
                        modes[platform].add("individual_fallback")
                    # Keep the batch error visible even when the individual call
                    # succeeds; it is operational evidence, not a skipped pair.
                    if component_results[platform]:
                        rows, error = component_results[platform][-1]
                        warning = f"GROUPED_SEARCH_FALLBACK:{type(batch_exc).__name__}"
                        component_results[platform][-1] = (rows, "; ".join(x for x in (error, warning) if x))

        for platform, parts in parts_by_platform.items():
            batched_types = set(batch_groups)
            for part in parts:
                if type(part) in batched_types and callable(getattr(part, "search_batch", None)):
                    continue
                platform_context = {**context, "query": query, "queries": [query], "platform": platform}
                try:
                    rows = part.search(platform_context)
                    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
                        raise TypeError("adapter.search must return list[dict]")
                    component_results[platform].append((rows, None))
                except Exception as exc:
                    component_results[platform].append(([], f"{type(exc).__name__}"))
                modes[platform].add("individual")

        for platform in platform_list:
            started = query_started
            platform_ref = hashlib.sha256(platform.encode("utf-8")).hexdigest()[:8]
            query_run_id = f"{run_id}:{query_ref}:{platform_ref}"
            parts = parts_by_platform[platform]
            if not parts:
                executions.append(QueryExecution(
                    SearchRun(query_run_id, query_ref, query, platform, started,
                              utc_now(), "BLOCKED", None, "NO_ADAPTER", "blocked"),
                    (),
                ))
                continue
            rows: list[dict[str, Any]] = []
            errors = [error for _, error in component_results[platform] if error]
            seen_urls: set[str] = set()
            for part_rows, _ in component_results[platform]:
                for item in part_rows:
                    identity = str(item.get("official_url") or item.get("posting_id") or repr(sorted(item.items())))
                    if identity in seen_urls:
                        continue
                    seen_urls.add(identity)
                    rows.append(item)
            if errors and rows:
                for item in rows:
                    item.setdefault("source_discovery_errors", []).extend(errors)
            status = "COMPLETED" if not errors or rows else "FAILED"
            mode = "+".join(sorted(modes[platform])) or "individual"
            executions.append(QueryExecution(
                SearchRun(query_run_id, query_ref, query, platform, started,
                          utc_now(), status, len(rows) if status == "COMPLETED" else None,
                          "; ".join(errors) if errors else None, mode),
                tuple(SearchHit(
                    hashlib.sha256(f"{platform}|{item.get('official_url') or item.get('posting_id') or repr(sorted(item.items()))}".encode()).hexdigest()[:20],
                    query_run_id, platform, query, item, utc_now(),
                ) for item in rows) if status == "COMPLETED" else (),
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
        # Query text can contain user-provided personal context. Persist only
        # opaque identifiers and operational metadata; the query lives in memory.
        "execution_records": [
            {
                "run_id": row.run.run_id,
                "query_id": row.run.query_id,
                "platform": row.run.platform,
                "started_at": row.run.started_at,
                "ended_at": row.run.ended_at,
                "status": row.run.status,
                "result_count": row.run.result_count,
                "error": row.run.error.split(":", 1)[0] if row.run.error else None,
                "execution_mode": row.run.execution_mode,
            }
            for row in rows
        ],
    }
