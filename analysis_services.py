"""Fail-closed HTTP client for the canonical evidence-analysis services.

The three analysis hooks are external dependencies, not local heuristics. Configure
an HTTPS service base URL, exact host allowlist, and API token via environment.
Responses are treated as untrusted data and minimally schema-checked; source claims
still require evidence review and are never inferred from a successful HTTP call.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen

SERVICE_PATHS = {
    "opportunity_state_resolution": "/v1/opportunity-state-resolution",
    "assessment_resolution": "/v1/assessment-resolution",
    "revalidation": "/v1/revalidation",
}


class AnalysisServiceConfigurationError(RuntimeError):
    pass


class AnalysisServiceRequestError(RuntimeError):
    pass


def _service_config() -> tuple[str, str, set[str], float]:
    base_url = os.getenv("RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL", "").strip().rstrip("/") + "/"
    token = os.getenv("RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN", "").strip()
    hosts = {
        value.strip().lower()
        for value in os.getenv("RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS", "").split(",")
        if value.strip()
    }
    try:
        timeout = float(os.getenv("RECRUIT_MATCH_ANALYSIS_SERVICE_TIMEOUT_SECONDS", "20"))
    except ValueError as exc:
        raise AnalysisServiceConfigurationError("ANALYSIS_SERVICE_TIMEOUT_INVALID") from exc
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise AnalysisServiceConfigurationError("ANALYSIS_SERVICE_BASE_URL_MUST_BE_HTTPS")
    if parsed.hostname.lower() not in hosts:
        raise AnalysisServiceConfigurationError("ANALYSIS_SERVICE_HOST_NOT_ALLOWLISTED")
    if not token:
        raise AnalysisServiceConfigurationError("ANALYSIS_SERVICE_TOKEN_MISSING")
    if not 2 <= timeout <= 60:
        raise AnalysisServiceConfigurationError("ANALYSIS_SERVICE_TIMEOUT_OUT_OF_RANGE")
    return base_url, token, hosts, timeout


def _invoke(stage: str, posting: dict[str, Any]) -> dict[str, Any]:
    base_url, token, hosts, timeout = _service_config()
    endpoint = urljoin(base_url, SERVICE_PATHS[stage].lstrip("/"))
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or parsed.hostname is None or parsed.hostname.lower() not in hosts:
        raise AnalysisServiceConfigurationError("ANALYSIS_SERVICE_ENDPOINT_NOT_ALLOWLISTED")
    payload = json.dumps({"stage": stage, "posting": posting}, ensure_ascii=False).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "recruit-match-analysis-client/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise AnalysisServiceRequestError("ANALYSIS_SERVICE_RESPONSE_TOO_LARGE")
            if response.status < 200 or response.status >= 300:
                raise AnalysisServiceRequestError(f"ANALYSIS_SERVICE_HTTP_{response.status}")
            result = json.loads(body.decode("utf-8"))
    except AnalysisServiceRequestError:
        raise
    except Exception as exc:
        raise AnalysisServiceRequestError(
            f"ANALYSIS_SERVICE_REQUEST_FAILED:{type(exc).__name__}"
        ) from exc
    if not isinstance(result, dict):
        raise AnalysisServiceRequestError("ANALYSIS_SERVICE_RESPONSE_MUST_BE_OBJECT")
    # Preserve explicit uncertainty. Never manufacture evidence, URLs, or a pass.
    for key in ("evidence_refs", "provenance_refs", "eligibility_evidence"):
        if key in result and (not isinstance(result[key], list) or any(not isinstance(v, str) for v in result[key])):
            raise AnalysisServiceRequestError(f"ANALYSIS_SERVICE_INVALID_FIELD:{key}")
    for key in ("authoritative_source", "decision_source_verified", "evidence_validation_passed"):
        if key in result and not isinstance(result[key], bool):
            raise AnalysisServiceRequestError(f"ANALYSIS_SERVICE_INVALID_FIELD:{key}")
    return result


def opportunity_state_resolution(posting: dict[str, Any]) -> dict[str, Any]:
    return _invoke("opportunity_state_resolution", posting)


def assessment_resolution(posting: dict[str, Any]) -> dict[str, Any]:
    return _invoke("assessment_resolution", posting)


def revalidation(posting: dict[str, Any]) -> dict[str, Any]:
    return _invoke("revalidation", posting)


SERVICES = {
    "opportunity_state_resolution": opportunity_state_resolution,
    "assessment_resolution": assessment_resolution,
    "revalidation": revalidation,
}


def readiness() -> dict[str, Any]:
    """Return configuration readiness without making network calls or exposing secrets."""
    try:
        base_url, _token, hosts, timeout = _service_config()
        return {
            "status": "CONFIGURED_NOT_LIVE_TESTED",
            "base_url": base_url,
            "allowed_hosts": sorted(hosts),
            "timeout_seconds": timeout,
            "required_stages": sorted(SERVICE_PATHS),
        }
    except AnalysisServiceConfigurationError as exc:
        return {
            "status": "BLOCKED",
            "reason": str(exc),
            "required_stages": sorted(SERVICE_PATHS),
        }
