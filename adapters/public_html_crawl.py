"""Policy-bounded public HTML discovery adapter ported from recruitment_matching.

This adapter is discovery-only. It requires explicit reviewed seed URLs/hosts,
checks robots.txt, uses HTTPS and same-host redirects, limits bytes and request
rate, and never infers open status or eligibility. Acquired HTML is retained as
a content-addressed artifact for downstream evidence review.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import urllib.robotparser
from typing import Any

from adapters.public_search import PLATFORM_DOMAINS

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "data" / "source_artifacts"
USER_AGENT = "recruit-match-public-discovery/1.0 (+https://github.com/ydonchoi/recruit_match)"


class CrawlConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CrawlConfig:
    platform: str
    seed_urls: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    terms_reviewed: bool
    request_delay_seconds: float = 2.0
    max_links_per_seed: int = 100
    max_html_bytes: int = 2 * 1024 * 1024
    timeout_seconds: float = 15.0


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href is not None:
            href = self.href.strip()
            title = " ".join(" ".join(self.text).split())
            if href and title:
                self.links.append((href, title))
            self.href, self.text = None, []


class NoCrossHostRedirect(HTTPRedirectHandler):
    def __init__(self, expected_netloc: str):
        self.expected_netloc = expected_netloc

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).netloc.lower() != self.expected_netloc.lower():
            raise PermissionError("CROSS_HOST_REDIRECT_DENIED")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def configs_from_environment() -> dict[str, CrawlConfig]:
    raw = os.getenv("RECRUIT_MATCH_CRAWL_CONFIG_JSON", "").strip()
    if not raw:
        return {}
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CrawlConfigurationError("RECRUIT_MATCH_CRAWL_CONFIG_JSON_INVALID") from exc
    if not isinstance(rows, list):
        raise CrawlConfigurationError("CRAWL_CONFIG_MUST_BE_JSON_ARRAY")
    configs = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CrawlConfigurationError("CRAWL_CONFIG_ENTRY_MUST_BE_OBJECT")
        platform = str(row.get("platform", "")).strip()
        seeds = tuple(str(x).strip() for x in row.get("seed_urls", []) if str(x).strip())
        hosts = tuple(str(x).lower().strip(".") for x in row.get("allowed_hosts", []) if str(x).strip())
        if platform not in PLATFORM_DOMAINS:
            raise CrawlConfigurationError(f"UNKNOWN_BASELINE_PLATFORM:{platform}")
        if platform in configs:
            raise CrawlConfigurationError(f"DUPLICATE_CRAWL_PLATFORM:{platform}")
        if not seeds or not hosts:
            raise CrawlConfigurationError(f"SEEDS_AND_HOST_ALLOWLIST_REQUIRED:{platform}")
        if row.get("terms_reviewed") is not True:
            # A missing terms review is not treated as permission to crawl.
            continue
        config = CrawlConfig(
            platform=platform, seed_urls=seeds, allowed_hosts=hosts,
            terms_reviewed=True,
            request_delay_seconds=max(1.0, float(row.get("request_delay_seconds", 2.0))),
            max_links_per_seed=min(500, max(1, int(row.get("max_links_per_seed", 100)))),
            max_html_bytes=min(5 * 1024 * 1024, max(1024, int(row.get("max_html_bytes", 2 * 1024 * 1024)))),
            timeout_seconds=min(30.0, max(2.0, float(row.get("timeout_seconds", 15.0)))),
        )
        for seed in seeds:
            _validate_url(seed, config.allowed_hosts)
        configs[platform] = config
    return configs


def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise PermissionError("HTTPS_URL_REQUIRED")
    if not any(host == item or host.endswith("." + item) for item in allowed_hosts):
        raise PermissionError("HOST_NOT_ALLOWLISTED")
    return host


class PublicHTMLCrawlAdapter:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self._last_request = 0.0

    def _fetch(self, url: str) -> tuple[str, str, bytes]:
        host = _validate_url(url, self.config.allowed_hosts)
        parsed = urlparse(url)
        # robots.txt is checked before every requested resource; network errors fail closed.
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        request = Request(robots_url, headers={"User-Agent": USER_AGENT}, method="GET")
        with build_opener(NoCrossHostRedirect(parsed.netloc)).open(request, timeout=self.config.timeout_seconds) as response:
            robots_body = response.read(512 * 1024 + 1)
        if len(robots_body) > 512 * 1024:
            raise PermissionError("ROBOTS_FILE_TOO_LARGE")
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(robots_body.decode("utf-8", errors="replace").splitlines())
        if not parser.can_fetch(USER_AGENT, url):
            raise PermissionError("ROBOTS_POLICY_DENIED")

        wait = self.config.request_delay_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}, method="GET")
        with build_opener(NoCrossHostRedirect(parsed.netloc)).open(request, timeout=self.config.timeout_seconds) as response:
            final_url = response.geturl()
            final_host = _validate_url(final_url, self.config.allowed_hosts)
            if final_host != host:
                raise PermissionError("CROSS_HOST_REDIRECT_DENIED")
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ValueError("NON_HTML_LISTING_RESPONSE")
            body = response.read(self.config.max_html_bytes + 1)
        self._last_request = time.monotonic()
        if len(body) > self.config.max_html_bytes:
            raise ValueError("HTML_BYTE_LIMIT_EXCEEDED")
        return final_url, content_type, body

    def search(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(context.get("query", "")).strip().casefold()
        if not self.config.terms_reviewed:
            raise CrawlConfigurationError("TERMS_REVIEW_REQUIRED")
        results = []
        seen = set()
        informative = tuple(token for token in query.split() if len(token) >= 2)
        for seed in self.config.seed_urls:
            final_url, _, body = self._fetch(seed)
            parser = AnchorParser()
            parser.feed(body.decode("utf-8", errors="replace"))
            for href, title in parser.links:
                url = urljoin(final_url, href)
                try:
                    _validate_url(url, self.config.allowed_hosts)
                except PermissionError:
                    continue
                if url in seen:
                    continue
                title_folded, url_folded = title.casefold(), url.casefold()
                # Discovery uses a loose token match; verification remains downstream.
                if informative and not any(token in title_folded or token in url_folded for token in informative):
                    continue
                seen.add(url)
                results.append(self._record(url, title, body))
                if len(results) >= self.config.max_links_per_seed:
                    break
        return results

    def _record(self, url: str, title: str, listing_body: bytes) -> dict[str, Any]:
        digest = hashlib.sha256(listing_body).hexdigest()
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        artifact_path = ARTIFACT_DIR / f"{digest}.html"
        if not artifact_path.exists():
            artifact_path.write_bytes(listing_body)
        host = (urlparse(url).hostname or "").lower()
        return {
            "institution": host,
            "title": title,
            "official_url": url,
            "application_status": "unknown",
            "eligibility_status": "unverified",
            "fit_assessment": "unassessed",
            "authoritative_source": False,
            "decision_source_verified": False,
            "evidence_refs": [url, f"sha256:{digest}"],
            "provenance_refs": [f"sha256:{digest}", f"artifact:{artifact_path.name}"],
            "candidate_recruitment_evidence_separated": False,
            "source_platform": self.config.platform,
            "source_type": "PUBLIC_HTML_DISCOVERY",
            "source_content_sha256": digest,
            "source_artifact": str(artifact_path.relative_to(ARTIFACT_DIR.parent)),
            "source_verification_required": True,
        }


class CompositeAdapter:
    """Run both API search and HTML crawl, retaining partial-source errors."""
    def __init__(self, platform: str, adapters: tuple[Any, ...]):
        self.PLATFORM = platform
        self.adapters = adapters
        self.last_errors: tuple[str, ...] = ()

    def search(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        hits, errors, seen = [], [], set()
        for adapter in self.adapters:
            try:
                rows = adapter.search(context)
                for row in rows:
                    url = str(row.get("official_url", "")).strip()
                    if url and url not in seen:
                        seen.add(url)
                        hits.append(row)
            except Exception as exc:
                errors.append(f"{type(adapter).__name__}:{type(exc).__name__}:{exc}")
        self.last_errors = tuple(errors)
        if errors:
            for row in hits:
                row["source_discovery_errors"] = list(errors)
        if not hits and errors:
            raise RuntimeError("ALL_PLATFORM_DISCOVERY_SOURCES_FAILED|" + "|".join(errors))
        return hits


def build_crawl_adapters() -> dict[str, PublicHTMLCrawlAdapter]:
    return {platform: PublicHTMLCrawlAdapter(config)
            for platform, config in configs_from_environment().items()}
