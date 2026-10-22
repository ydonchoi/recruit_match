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

DEFAULT_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
DEFAULT_HOSTS = {"api.bing.microsoft.com"}

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
    result_count: int = 10
    delay_seconds: float = 0.25


def _config() -> SearchConfig:
    endpoint = os.getenv("RECRUIT_MATCH_SEARCH_ENDPOINT", DEFAULT_ENDPOINT).strip()
    key = os.getenv("RECRUIT_MATCH_SEARCH_API_KEY", "").strip()
    parsed = urlparse(endpoint)
    allowed_hosts = {h.strip().lower() for h in os.getenv("RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS", ",".join(DEFAULT_HOSTS)).split(",") if h.strip()}
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        raise AdapterConfigurationError("Search endpoint must be HTTPS and its host must be explicitly allowlisted.")
    if not key:
        raise AdapterConfigurationError("Set RECRUIT_MATCH_SEARCH_API_KEY to enable the search adapter.")
    return SearchConfig(endpoint=endpoint, api_key=key)


class PublicSearchAdapter:
    def __init__(self, platform: str, domains: tuple[str, ...]):
        self.PLATFORM = platform
        self.domains = domains
        self._last_request_at = 0.0

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
            now = time.monotonic()
            wait = config.delay_seconds - (now - self._last_request_at)
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
                raise SearchProviderError(f"Search provider request failed: {type(exc).__name__}: {exc}") from exc
            self._last_request_at = time.monotonic()
            pages = payload.get("webPages", {}).get("value", [])
            for item in pages:
                url = str(item.get("url", "")).strip()
                if not url or url in seen_urls or urlparse(url).scheme != "https":
                    continue
                seen_urls.add(url)
                host = (urlparse(url).hostname or "").lower()
                domain_match = bool(self.domains) and any(host == d or host.endswith("." + d) for d in self.domains)
                results.append({
                    "institution": str(item.get("siteName") or host or self.PLATFORM),
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
                    "source_platform": self.PLATFORM,
                    "search_provider": "bing_web_search_compatible_api",
                    "domain_match": domain_match,
                    "search_snippet": str(item.get("snippet", "")),
                    "source_verification_required": True,
                })
        return results


ADAPTERS = {
    platform: PublicSearchAdapter(platform, domains)
    for platform, domains in PLATFORM_DOMAINS.items()
}
