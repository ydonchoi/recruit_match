"""Policy-bounded web search adapter factory for recruitment platforms.

This adapter uses a configured Bing Web Search-compatible JSON API as a
discovery index, then tags results by the requested recruitment channel.
It does NOT crawl target sites, bypass access controls, or claim official
verification. API credentials are read only from environment variables.
"""
from __future__ import annotations
import json
import os
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from dataclasses import dataclass
from typing import Any

DEFAULT_ENDPOINT = ""
DEFAULT_HOSTS: set[str] = set()

PLATFORM_DOMAINS = {
    "JOB-ALIO": ("job.alio.go.kr", "alio.go.kr"),
    "NKIS": ("nkis.re.kr",),
    "나라일터": ("gojobs.go.kr", "gosi.kr"),
    "고용24": ("work24.go.kr",),
    "사람인": ("saramin.co.kr",),
    "잡코리아": ("jobkorea.co.kr",),
    "클린아이 잡플러스": ("cleaneye.go.kr",),
    "대학 공식 채용 페이지": (),  # no single domain; query is restricted by institution/user terms
    "하이브레인넷": ("hibrain.net",),
    "연구기관 공식 채용 페이지": (),  # multi-domain; results require subsequent official-source verification
    "KEDI": ("kedi.re.kr",),
    "KICE": ("kice.re.kr",),
}


class AdapterConfigurationError(RuntimeError):
    pass


class SearchProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchConfig:
    endpoint: str
    api_key: str
    timeout_seconds: float = 15.0
    result_count: int = 50
    delay_seconds: float = 0.25


def _config() -> SearchConfig:
    endpoint = os.getenv("RECRUIT_MATCH_SEARCH_ENDPOINT", DEFAULT_ENDPOINT).strip()
    key = os.getenv("RECRUIT_MATCH_SEARCH_API_KEY", "").strip()
    parsed = urlparse(endpoint)
    allowed_hosts = {h.strip().lower() for h in os.getenv("RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS", ",".join(DEFAULT_HOSTS)).split(",") if h.strip()}
    if not endpoint:
        raise AdapterConfigurationError("Set RECRUIT_MATCH_SEARCH_ENDPOINT to an HTTPS search API endpoint.")
    if parsed.scheme != "https" or not parsed.hostname or not allowed_hosts or parsed.hostname.lower() not in allowed_hosts:
        raise AdapterConfigurationError("Search endpoint must be HTTPS and its host must be explicitly allowlisted in RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS.")
    if not key:
        raise AdapterConfigurationError("Set RECRUIT_MATCH_SEARCH_API_KEY to enable the search adapter.")
    try:
        result_count = int(os.getenv("RECRUIT_MATCH_SEARCH_RESULT_COUNT", "50"))
    except ValueError as exc:
        raise AdapterConfigurationError("RECRUIT_MATCH_SEARCH_RESULT_COUNT must be an integer from 1 to 50.") from exc
    return SearchConfig(endpoint=endpoint, api_key=key,
                        result_count=min(max(result_count, 1), 50))


class PublicSearchAdapter:
    """Search adapter that can share one provider request across platforms."""

    def __init__(self, platform: str, domains: tuple[str, ...]):
        self.PLATFORM = platform
        self.domains = domains
        self._last_request_at = 0.0

    @staticmethod
    def _matches_domain(host: str, domains: tuple[str, ...]) -> bool:
        host = host.lower().rstrip(".")
        return any(host == domain or host.endswith("." + domain) for domain in domains)

    def _fetch_pages(self, query: str, config: SearchConfig) -> list[dict[str, Any]]:
        wait = config.delay_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        params = urlencode({"q": query, "count": min(max(config.result_count, 1), 50), "mkt": "ko-KR", "responseFilter": "Webpages"})
        request = Request(
            config.endpoint + ("&" if "?" in config.endpoint else "?") + params,
            headers={"Ocp-Apim-Subscription-Key": config.api_key, "Accept": "application/json", "User-Agent": "recruit-match/1.0"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=config.timeout_seconds) as response:
                body = response.read(5 * 1024 * 1024 + 1)
                if len(body) > 5 * 1024 * 1024:
                    raise SearchProviderError("Search API response exceeds 5 MiB.")
                payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            # URL errors may echo the complete request URL, including user
            # supplied search text. Keep provider errors safe for run logs.
            raise SearchProviderError(f"Search provider request failed ({type(exc).__name__}).") from exc
        self._last_request_at = time.monotonic()
        pages = payload.get("webPages", {}).get("value", [])
        if not isinstance(pages, list):
            raise SearchProviderError("Search API webPages.value must be an array.")
        return [item for item in pages if isinstance(item, dict)]

    def _posting(self, item: dict[str, Any], platform: str,
                 domains: tuple[str, ...]) -> dict[str, Any] | None:
        url = str(item.get("url", "")).strip()
        parsed = urlparse(url)
        if not url or parsed.scheme != "https" or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        domain_match = self._matches_domain(host, domains)
        # A platform-scoped query must not silently accept results from a
        # different channel just because the provider ignored its site filter.
        if domains and not domain_match:
            return None
        return {
            "institution": str(item.get("siteName") or host or platform),
            "title": str(item.get("name") or "제목 미확인"),
            "official_url": url,
            "alternate_source_urls": [],
            "application_status": "unknown",
            "eligibility_status": "unverified",
            "fit_assessment": "unassessed",
            "authoritative_source": False,
            "decision_source_verified": False,
            "evidence_refs": [url],
            "provenance_refs": [url],
            "candidate_recruitment_evidence_separated": False,
            "source_platform": platform,
            "search_provider": "bing_web_search_compatible_api",
            "domain_match": domain_match,
            "search_snippet": str(item.get("snippet", "")),
            "source_verification_required": True,
        }

    def search_batch(self, context: dict[str, Any],
                     adapters: dict[str, "PublicSearchAdapter"]) -> dict[str, list[dict[str, Any]]]:
        """Search all mapped domains together, then route hits to each platform.

        Platforms without a single registered domain share one broad request,
        matching the prior behavior while avoiding duplicate provider calls.
        """
        config = _config()
        base_query = str(context.get("query", "")).strip()
        if not base_query:
            return {platform: [] for platform in adapters}
        all_domains = tuple(sorted({
            domain for adapter in adapters.values() for domain in adapter.domains
        }))
        domain_pages: list[dict[str, Any]] = []
        if all_domains:
            domain_query = base_query + " (" + " OR ".join("site:" + domain for domain in all_domains) + ")"
            domain_pages = self._fetch_pages(domain_query, config)

        broad_platforms = [platform for platform, adapter in adapters.items() if not adapter.domains]
        broad_pages: list[dict[str, Any]] = []
        if broad_platforms:
            broad_pages = self._fetch_pages(base_query, config)

        routed = {platform: [] for platform in adapters}
        known_domains = tuple(all_domains)
        for platform, adapter in adapters.items():
            pages = broad_pages if not adapter.domains else domain_pages
            seen_urls: set[str] = set()
            for item in pages:
                host = (urlparse(str(item.get("url", ""))).hostname or "").lower()
                if not adapter.domains and self._matches_domain(host, known_domains):
                    continue
                row = adapter._posting(item, platform, adapter.domains)
                if row is None or row["official_url"] in seen_urls:
                    continue
                seen_urls.add(row["official_url"])
                routed[platform].append(row)
        return routed

    def search(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        config = _config()
        queries = context.get("queries") or [context.get("query", "")]
        if not isinstance(queries, list):
            raise TypeError("queries must be a list")
        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for base_query in queries:
            query = str(base_query).strip()
            if not query:
                continue
            if self.domains:
                query += " (" + " OR ".join("site:" + d for d in self.domains) + ")"
            pages = self._fetch_pages(query, config)
            for item in pages:
                row = self._posting(item, self.PLATFORM, self.domains)
                if row is None or row["official_url"] in seen_urls:
                    continue
                seen_urls.add(row["official_url"])
                results.append(row)
        return results


ADAPTERS = {
    platform: PublicSearchAdapter(platform, domains)
    for platform, domains in PLATFORM_DOMAINS.items()
}
