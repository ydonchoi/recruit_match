"""Read-only Notion REST API adapter with server-side filtering and rate limiting.

Why this exists
---------------
Agents that read Notion through the hosted MCP connector can exhaust the
workspace quota for SQL-mode ``query-data-sources`` calls. This adapter calls
the public REST API directly with a personal integration token, so reads are
governed by the general REST limit (an average of about 3 requests per second
per integration) instead of that MCP quota.

Boundaries
----------
* Read-only: only data-source queries and database/data-source retrieval are
  implemented. There is no create/update/delete path.
* Fail-closed: without ``NOTION_TOKEN`` the adapter raises
  ``NotionConfigurationError`` instead of returning an empty result.
* The host is fixed to ``api.notion.com``; the token is read only from the
  environment and is never echoed in error messages.
* Filtering happens on the server (Notion ``filter`` / ``sorts`` /
  ``filter_properties``) and the number of pages fetched is capped, so a call
  never silently downloads a whole database.

Stdlib only; ``opener``/``clock``/``sleep`` are injectable for tests.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_HOST = "api.notion.com"
API_BASE = f"https://{API_HOST}/v1"
DEFAULT_NOTION_VERSION = "2025-09-03"
MAX_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 5
HARD_MAX_PAGES = 50
MAX_REQUESTS_PER_SECOND = 3.0
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_ID_RE = re.compile(r"([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12})")


class NotionConfigurationError(RuntimeError):
    pass


class NotionAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def normalize_id(value: str) -> str:
    """Extract a Notion UUID from a raw id, ``collection://`` URL or page URL.

    For a page/database URL, the id in the path is used; a ``?v=`` view id is
    ignored because views are not part of the REST query contract.
    """
    text = str(value or "").strip()
    path = text.split("?", 1)[0]
    matches = _ID_RE.findall(path)
    if not matches:
        raise ValueError("Not a recognizable Notion id or URL.")
    raw = matches[-1].replace("-", "").lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


@dataclass
class RateLimiter:
    """Minimum-interval limiter that keeps the average at or below 3 req/s."""

    requests_per_second: float = MAX_REQUESTS_PER_SECOND
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not 0 < self.requests_per_second <= MAX_REQUESTS_PER_SECOND:
            raise NotionConfigurationError("requests_per_second must be in (0, 3].")

    def wait(self) -> None:
        interval = 1.0 / self.requests_per_second
        if self._last is not None:
            remaining = interval - (self.clock() - self._last)
            if remaining > 0:
                self.sleep(remaining)
        self._last = self.clock()


@dataclass(frozen=True)
class NotionConfig:
    token: str
    notion_version: str = DEFAULT_NOTION_VERSION
    timeout_seconds: float = 20.0
    max_retries: int = 3
    requests_per_second: float = MAX_REQUESTS_PER_SECOND


def config_from_env() -> NotionConfig:
    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        raise NotionConfigurationError(
            "Set NOTION_TOKEN to a Notion integration token (share the target "
            "pages/databases with that integration first)."
        )
    try:
        rps = float(os.getenv("NOTION_MAX_RPS", str(MAX_REQUESTS_PER_SECOND)))
    except ValueError as exc:
        raise NotionConfigurationError("NOTION_MAX_RPS must be a number in (0, 3].") from exc
    if not 0 < rps <= MAX_REQUESTS_PER_SECOND:
        raise NotionConfigurationError("NOTION_MAX_RPS must be a number in (0, 3].")
    version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip() or DEFAULT_NOTION_VERSION
    return NotionConfig(token=token, notion_version=version, requests_per_second=rps)


# --------------------------------------------------------------------------
# Server-side filter helpers (Notion REST filter object shapes)
# --------------------------------------------------------------------------

def prop_filter(prop: str, prop_type: str, operator: str, value: Any = True) -> dict[str, Any]:
    """One property filter, e.g. ``prop_filter("상태", "status", "equals", "진행")``."""
    if not prop or not prop_type or not operator:
        raise ValueError("property, type and operator are required")
    return {"property": prop, prop_type: {operator: value}}


def date_range_filter(prop: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Inclusive ISO date range on a date property (either bound may be omitted)."""
    parts = []
    if start:
        parts.append(prop_filter(prop, "date", "on_or_after", start))
    if end:
        parts.append(prop_filter(prop, "date", "on_or_before", end))
    if not parts:
        raise ValueError("date_range_filter needs start and/or end")
    return parts[0] if len(parts) == 1 else {"and": parts}


def all_of(*filters: dict[str, Any]) -> dict[str, Any]:
    items = [f for f in filters if f]
    if not items:
        raise ValueError("all_of needs at least one filter")
    return items[0] if len(items) == 1 else {"and": items}


def any_of(*filters: dict[str, Any]) -> dict[str, Any]:
    items = [f for f in filters if f]
    if not items:
        raise ValueError("any_of needs at least one filter")
    return items[0] if len(items) == 1 else {"or": items}


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class NotionReadClient:
    """Read-only client for ``api.notion.com``."""

    _ALLOWED = (
        ("GET", re.compile(r"^/v1/(databases|data_sources|pages)/[0-9a-f-]{36}$")),
        ("POST", re.compile(r"^/v1/data_sources/[0-9a-f-]{36}/query$")),
        ("POST", re.compile(r"^/v1/databases/[0-9a-f-]{36}/query$")),
    )

    def __init__(self, config: NotionConfig, opener: Callable[..., Any] = urlopen,
                 limiter: RateLimiter | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self._opener = opener
        self._sleep = sleep
        self.limiter = limiter or RateLimiter(config.requests_per_second, sleep=sleep)
        self.request_count = 0

    @classmethod
    def from_env(cls, **kwargs: Any) -> "NotionReadClient":
        return cls(config_from_env(), **kwargs)

    # -- transport -------------------------------------------------------
    def _request(self, method: str, path: str, body: dict[str, Any] | None = None,
                 query: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        if not any(method == m and rx.match(path) for m, rx in self._ALLOWED):
            raise NotionConfigurationError("Only read-only Notion endpoints are permitted.")
        url = "https://" + API_HOST + path + ("?" + urlencode(query) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Notion-Version": self.config.notion_version,
            "Accept": "application/json",
            "User-Agent": "recruit-match/1.0",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        attempt = 0
        while True:
            self.limiter.wait()
            self.request_count += 1
            try:
                with self._opener(Request(url, data=data, headers=headers, method=method),
                                  timeout=self.config.timeout_seconds) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise NotionAPIError("Notion response exceeds 10 MiB.")
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise NotionAPIError("Notion response must be a JSON object.")
                return payload
            except HTTPError as exc:
                status = exc.code
                code, message = self._error_details(exc)
                if status in RETRYABLE_STATUS and attempt < self.config.max_retries:
                    attempt += 1
                    self._sleep(self._retry_delay(exc, attempt))
                    continue
                raise NotionAPIError(f"Notion API {status} {code or ''}: {message}".strip(),
                                     status=status, code=code) from None
            except NotionAPIError:
                raise
            except Exception as exc:  # network/JSON errors: keep message token-free
                raise NotionAPIError(f"Notion request failed ({type(exc).__name__}).") from None

    @staticmethod
    def _retry_delay(exc: HTTPError, attempt: int) -> float:
        header = exc.headers.get("Retry-After") if exc.headers else None
        try:
            if header is not None:
                return min(max(float(header), 0.0), 60.0)
        except ValueError:
            pass
        return min(2.0 ** attempt, 30.0)

    @staticmethod
    def _error_details(exc: HTTPError) -> tuple[str | None, str]:
        try:
            body = json.loads(exc.read(64 * 1024).decode("utf-8"))
            return body.get("code"), str(body.get("message", ""))[:300]
        except Exception:
            return None, "unreadable error body"

    # -- read operations -------------------------------------------------
    def retrieve_database(self, database_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/databases/{normalize_id(database_id)}")

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/data_sources/{normalize_id(data_source_id)}")

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/pages/{normalize_id(page_id)}")

    def resolve_data_source_ids(self, database_id: str) -> list[str]:
        """Database (container) id -> its data source ids (API 2025-09-03)."""
        sources = self.retrieve_database(database_id).get("data_sources") or []
        ids = [normalize_id(s["id"]) for s in sources if isinstance(s, dict) and s.get("id")]
        if not ids:
            raise NotionAPIError("Database exposes no data sources to this integration.")
        return ids

    def query(self, data_source_id: str, *, filter: dict[str, Any] | None = None,
              sorts: list[dict[str, Any]] | None = None,
              filter_properties: list[str] | None = None,
              page_size: int = MAX_PAGE_SIZE, max_pages: int = DEFAULT_MAX_PAGES,
              legacy_database: bool = False) -> dict[str, Any]:
        """Server-side filtered query with bounded pagination.

        Returns ``{"results": [...], "has_more": bool, "next_cursor": str|None,
        "pages_fetched": int, "truncated": bool}``. ``truncated`` is True when
        ``max_pages`` stopped pagination before Notion reported the end, so a
        caller can never mistake a capped read for a complete one.
        """
        if not 1 <= int(page_size) <= MAX_PAGE_SIZE:
            raise ValueError("page_size must be 1..100")
        if not 1 <= int(max_pages) <= HARD_MAX_PAGES:
            raise ValueError(f"max_pages must be 1..{HARD_MAX_PAGES}")
        target = normalize_id(data_source_id)
        path = (f"/v1/databases/{target}/query" if legacy_database
                else f"/v1/data_sources/{target}/query")
        query_params = [("filter_properties", p) for p in (filter_properties or [])]
        body: dict[str, Any] = {"page_size": int(page_size)}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        has_more = False
        while pages < max_pages:
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request("POST", path, body, query_params or None)
            pages += 1
            batch = payload.get("results") or []
            results.extend(r for r in batch if isinstance(r, dict))
            has_more = bool(payload.get("has_more"))
            cursor = payload.get("next_cursor") if has_more else None
            if not has_more or not cursor:
                break
        return {"results": results, "has_more": has_more, "next_cursor": cursor,
                "pages_fetched": pages, "truncated": has_more}


# --------------------------------------------------------------------------
# Result simplification (compact output for agents)
# --------------------------------------------------------------------------

def _plain(rich: Any) -> str:
    if not isinstance(rich, list):
        return ""
    return "".join(str(part.get("plain_text", "")) for part in rich if isinstance(part, dict))


def simplify_property(prop: dict[str, Any]) -> Any:
    kind = prop.get("type")
    value = prop.get(kind) if kind else None
    if kind in {"title", "rich_text"}:
        return _plain(value)
    if kind in {"select", "status"}:
        return value.get("name") if isinstance(value, dict) else None
    if kind == "multi_select":
        return [v.get("name") for v in value or [] if isinstance(v, dict)]
    if kind == "date":
        return {"start": value.get("start"), "end": value.get("end")} if isinstance(value, dict) else None
    if kind in {"number", "checkbox", "url", "email", "phone_number",
                "created_time", "last_edited_time"}:
        return value
    if kind == "relation":
        return [v.get("id") for v in value or [] if isinstance(v, dict)]
    if kind == "people":
        return [v.get("id") for v in value or [] if isinstance(v, dict)]
    if kind == "unique_id" and isinstance(value, dict):
        prefix = value.get("prefix")
        return f"{prefix}-{value.get('number')}" if prefix else value.get("number")
    if kind == "formula" and isinstance(value, dict):
        return value.get(value.get("type"))
    if kind == "rollup" and isinstance(value, dict):
        return value.get(value.get("type"))
    return {"type": kind, "unsupported": True}


def simplify_page(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties") or {}
    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "last_edited_time": page.get("last_edited_time"),
        "properties": {name: simplify_property(p) for name, p in props.items() if isinstance(p, dict)},
    }


# --------------------------------------------------------------------------
# CLI: lets an agent run one bounded REST query instead of MCP SQL calls
# --------------------------------------------------------------------------

def _parse_where(items: list[str]) -> list[dict[str, Any]]:
    """``--where 'PROP|TYPE|OPERATOR|VALUE'`` (VALUE parsed as JSON when possible)."""
    out = []
    for item in items:
        parts = item.split("|", 3)
        if len(parts) < 3:
            raise ValueError("--where must be PROP|TYPE|OPERATOR[|VALUE]")
        prop, ptype, op = parts[:3]
        value: Any = True
        if len(parts) == 4:
            try:
                value = json.loads(parts[3])
            except json.JSONDecodeError:
                value = parts[3]
        out.append(prop_filter(prop, ptype, op, value))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m adapters.notion_api",
                                description="Read-only Notion REST query (needs NOTION_TOKEN).")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("query", help="Server-side filtered data source query")
    target = q.add_mutually_exclusive_group(required=True)
    target.add_argument("--data-source", help="data source id or collection:// URL")
    target.add_argument("--database", help="database id/URL; resolved to its data source")
    q.add_argument("--where", action="append", default=[],
                   help="PROP|TYPE|OPERATOR|VALUE, e.g. '상태|status|equals|\"진행\"' (repeatable, AND)")
    q.add_argument("--any", action="store_true", help="combine --where filters with OR instead of AND")
    q.add_argument("--date-prop", help="date property for --since/--until")
    q.add_argument("--since", help="inclusive start date YYYY-MM-DD")
    q.add_argument("--until", help="inclusive end date YYYY-MM-DD")
    q.add_argument("--filter-json", help="raw Notion filter object (overrides --where/--since)")
    q.add_argument("--sort", action="append", default=[],
                   help="PROP:ascending|descending (repeatable)")
    q.add_argument("--property", action="append", default=[], dest="properties",
                   help="return only this property id (repeatable; maps to filter_properties)")
    q.add_argument("--page-size", type=int, default=50)
    q.add_argument("--max-pages", type=int, default=1)
    q.add_argument("--raw", action="store_true", help="print raw Notion pages instead of simplified rows")
    q.add_argument("--legacy-database-endpoint", action="store_true",
                   help="use POST /v1/databases/{id}/query (needs NOTION_VERSION=2022-06-28)")
    g = sub.add_parser("get", help="Retrieve one page/database/data source")
    g.add_argument("kind", choices=["page", "database", "data-source"])
    g.add_argument("id")
    return p


def _build_filter(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.filter_json:
        value = json.loads(args.filter_json)
        if not isinstance(value, dict):
            raise ValueError("--filter-json must be a JSON object")
        return value
    parts = _parse_where(args.where)
    if args.since or args.until:
        if not args.date_prop:
            raise ValueError("--since/--until require --date-prop")
        parts.append(date_range_filter(args.date_prop, args.since, args.until))
    if not parts:
        return None
    return any_of(*parts) if args.any else all_of(*parts)


def main(argv: list[str] | None = None, client: NotionReadClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = client or NotionReadClient.from_env()
        if args.command == "get":
            fn = {"page": client.retrieve_page, "database": client.retrieve_database,
                  "data-source": client.retrieve_data_source}[args.kind]
            print(json.dumps(fn(args.id), ensure_ascii=False, indent=2))
            return 0
        sorts = []
        for item in args.sort:
            prop, _, direction = item.rpartition(":")
            if not prop or direction not in {"ascending", "descending"}:
                raise ValueError("--sort must be PROP:ascending|descending")
            sorts.append({"property": prop, "direction": direction})
        if args.database and not args.legacy_database_endpoint:
            ids = client.resolve_data_source_ids(args.database)
            if len(ids) != 1:
                raise ValueError(f"Database has {len(ids)} data sources; pass --data-source explicitly.")
            target = ids[0]
        else:
            target = args.data_source or args.database
        result = client.query(target, filter=_build_filter(args), sorts=sorts or None,
                              filter_properties=args.properties or None,
                              page_size=args.page_size, max_pages=args.max_pages,
                              legacy_database=args.legacy_database_endpoint)
        rows = result["results"] if args.raw else [simplify_page(r) for r in result["results"]]
        print(json.dumps({"rows": rows, "count": len(rows), "has_more": result["has_more"],
                          "next_cursor": result["next_cursor"], "truncated": result["truncated"],
                          "requests": client.request_count}, ensure_ascii=False, indent=2))
        return 0
    except (NotionConfigurationError, NotionAPIError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
