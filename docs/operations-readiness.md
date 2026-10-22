# Baseline platform integration and operational readiness

Status: **Configuration prepared; live operation blocked until external credentials and policy reviews are supplied.**
Scope: all 12 values in `run_pipeline.py::BASELINE_PLATFORMS`.
This document distinguishes implemented connector code from external access and live verification.

## Baseline inventory

| Baseline platform | Current adapter path | Host scope in code | Operational blocker / gate |
|---|---|---|---|
| JOB-ALIO | Shared public-search API; optional reviewed HTML discovery | `job.alio.go.kr`, `alio.go.kr` | Search API credentials required; HTML terms/robots must be reviewed |
| NKIS | Shared public-search API; optional reviewed HTML discovery | `nkis.re.kr` | Search API credentials required; HTML terms/robots must be reviewed |
| 나라일터 | Shared public-search API; optional reviewed HTML discovery | `gojobs.go.kr`, `gosi.kr` | Search API credentials required; confirm canonical official host and terms |
| 고용24 | Shared public-search API; optional reviewed HTML discovery | `work24.go.kr` | Search API credentials required; official API requires separately approved credentials if used |
| 사람인 | Shared public-search API; optional reviewed HTML discovery | `saramin.co.kr` | Search API credentials required; terms/robots review required |
| 잡코리아 | Shared public-search API; optional reviewed HTML discovery | `jobkorea.co.kr` | Search API credentials required; terms/robots review required |
| 클린아이 잡플러스 | Shared public-search API; optional reviewed HTML discovery | `cleaneye.go.kr` | Search API credentials required; verify current official host and terms |
| 대학 공식 채용 페이지 | Shared public-search API | No single host | Institution-specific official URL/host must be explicitly reviewed; no generic crawler config |
| 하이브레인넷 | Shared public-search API; optional reviewed HTML discovery | `hibrain.net` | Search API credentials required; terms/robots review required |
| 연구기관 공식 채용 페이지 | Shared public-search API | Multi-domain | Each institution requires an explicit official host and policy review |
| KEDI | Shared public-search API; optional reviewed HTML discovery | `kedi.re.kr` | Search API credentials required; terms/robots review required |
| KICE | Shared public-search API; optional reviewed HTML discovery | `kice.re.kr` | Search API credentials required; terms/robots review required |

The shared public-search adapter is an index/discovery layer, not an official-source validator. It needs `RECRUIT_MATCH_SEARCH_ENDPOINT`, `RECRUIT_MATCH_SEARCH_API_KEY`, and `RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS`. It is only Bing Web Search-compatible; arbitrary search APIs are not plug-compatible without a parser.

## Analysis service contract

`analysis_services.py` now supplies the three required hooks consumed by `analysis_pipeline.py`:

- `POST /v1/opportunity-state-resolution`
- `POST /v1/assessment-resolution`
- `POST /v1/revalidation`

Each request sends `{"stage":"…","posting":{…}}` over HTTPS with a bearer token. The service host must exactly match `RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS`. Responses must be JSON objects; evidence arrays and boolean fields are type-checked. A successful HTTP response alone does not mark a posting verified. The remote service must return explicit evidence and provenance, and the canonical pipeline still applies its own evidence/eligibility/writer gates.

Required environment:
- `RECRUIT_MATCH_ANALYSIS_SERVICE_BASE_URL`
- `RECRUIT_MATCH_ANALYSIS_SERVICE_ALLOWED_HOSTS`
- `RECRUIT_MATCH_ANALYSIS_SERVICE_TOKEN`
- optional `RECRUIT_MATCH_ANALYSIS_SERVICE_TIMEOUT_SECONDS` (2–60 seconds)

Use `.env.example` only as a template. Store real tokens in the deployment secret manager or GitHub Actions secrets, never in source control.

## Activation order

1. Supply an approved search-provider endpoint, key, and exact host allowlist.
2. Review the official URL, robots policy, terms, rate limits, and permitted use for each HTML source. Only then add a crawl entry with `terms_reviewed: true`; this is an operator attestation, not a legal determination.
3. Supply and contract-test the three analysis endpoints. Verify that they return citations to official source material and preserve UNKNOWN/HOLD when evidence is missing.
4. Run CI unit tests, then a controlled live smoke test with low request volume.
5. Inspect the per-platform execution records and artifacts. Only mark a platform operational after observed live evidence exists.

## Honest current status

No search-provider key, analysis service URL/token, or operator-confirmed site terms review is present in this repository. Therefore no live search or official-posting verification can be claimed from these files alone. Missing credentials are expected to result in BLOCKED/partial status rather than zero results or success. A configured endpoint is not a tested endpoint; a passing mock test is not a live-source test.
