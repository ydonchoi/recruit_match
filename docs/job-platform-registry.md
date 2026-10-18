# Recruitment Search Platform Registry

Status: **CATALOG IMPLEMENTED / LIVE PROVIDERS NOT CONFIGURED**

The machine-readable catalog is maintained in
[`src/recruit_match/platform_registry.py`](../src/recruit_match/platform_registry.py).
It is a provider-neutral source inventory, not a web crawler or a claim that
every listed platform can be queried automatically.

## Registered sources

| ID | Platform | Search domain | Priority | Access evidence | Notes |
|---|---|---|---:|---|---|
| `saramin` | 사람인 | General / career | 1 | Official API documentation identified | API key, terms and limits must be configured and rechecked |
| `work24` | 고용24 | General / public employment / regional | 1 | Official Open API guide identified | Authentication, response schema and limits require validation |
| `alio_job` | 잡알리오·ALIO | Public institutions | 1 | Website identified | Public API and automated-access conditions unverified |
| `gojobs` | 나라일터 | Civil service / public employment | 1 | Website identified | API and automated-access conditions unverified |
| `cleaneye_jobplus` | 클린아이 잡플러스 | Local public institutions | 1 | Website identified | API availability unverified |
| `hibrain` | 하이브레인넷 | University faculty / research | 1 | Website identified | Automated-access conditions unverified |
| `university_official_boards` | University official recruitment boards | Faculty / staff / research | 1 | Institution discovery aid identified | Each institution's original recruitment URL must be registered separately |
| `rndjob` | 이공계인력중개센터 | Research / career | 2 | Website identified | API and automated-access conditions unverified |
| `jobaba` | 잡아바 | Regional / general / public employment | 2 | Official API guide identified | Regional scope, authentication and limits require validation |
| `jobkorea` | 잡코리아 | General / career | 2 | Website identified | Public search API and automated-access conditions unverified |
| `wanted` | 원티드 | Career / developer | 2 | Website identified | External search API access unverified |
| `remember` | 리멤버 | Career | 2 | Website identified | External search API access unverified |
| `jumpit` | 점핏 | Developer / career | 2 | Website identified | Automated-access conditions unverified |
| `linkedin_jobs` | LinkedIn Jobs | Global / career | 3 | Jobs website identified | API permissions and terms unverified |

Priority is a proposed integration order, not a measured ranking of coverage or
quality. `api_documented` means that API documentation was identified; it does
not mean credentials exist, the API was called, or the adapter is operational.
All non-API sources remain candidates until access conditions are checked.

## Selection boundary

Call `select_platforms(categories)` with normalized domain categories. The
catalog does not depend on the Search Matrix's internal object shape or number
of combinations. Search Matrix planning, call-budget enforcement, platform
selection and provider execution remain separate responsibilities.

Example:

```python
from recruit_match.platform_registry import select_platforms

public_sources = select_platforms(
    ("public_institution", "civil_service", "public_employment")
)
university_sources = select_platforms(
    ("university_faculty", "university_staff", "research")
)
```

The selection functions only return catalog metadata. They do not perform a
network request. The existing shared Search Agent call budget remains 20 by
default and 100 maximum; any real adapter must also respect source-specific
quotas, authentication, terms and access policies.

## Safety and evidence rules

- Do not bypass authentication, CAPTCHA, access controls, or anti-bot measures.
- Prefer documented and authorized APIs where available.
- Do not mark a source connected merely because its URL or API documentation is listed.
- Preserve provider identity, query/combination ID, observation time, original URL,
  and retrieval outcome for every actual search.
- Normalize provider results only after retrieval; source discovery is not
  authoritative-source verification or proof that a vacancy is current.
- For universities, keep a maintained institution-to-official-board mapping.
  The Academy Info site is a discovery aid, not a unified job-posting API.
- Treat unknown access policy or API status as unverified and fail closed before
  automated acquisition.

## Verification status

Unit tests cover catalog uniqueness, metadata invariants, category filtering,
public/university source selection and invalid input rejection. They are authored
but have not been executed in this change.
