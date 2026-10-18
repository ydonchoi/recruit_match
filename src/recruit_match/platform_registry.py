"""Provider-neutral catalog of candidate recruitment search platforms.

This module stores source metadata only. It does not fetch job postings, assert
that a source is authorized for automated access, or configure a live provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from typing import Iterable


CATEGORIES = frozenset({
    "general",
    "career",
    "developer",
    "public_employment",
    "public_institution",
    "civil_service",
    "university_faculty",
    "university_staff",
    "research",
    "regional_employment",
    "global",
})
ACCESS_MODES = frozenset({"api", "web", "institution_specific"})
INTEGRATION_STATUSES = frozenset({
    "api_documented",
    "candidate_unverified",
    "manual_registration_required",
})


@dataclass(frozen=True, slots=True)
class PlatformSource:
    """A candidate source and its explicitly bounded integration evidence."""

    platform_id: str
    name: str
    categories: tuple[str, ...]
    homepage_url: str | None
    access_mode: str
    integration_status: str
    priority: int
    api_docs_url: str | None = None
    discovery_url: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.platform_id or not self.platform_id.replace("_", "").isalnum():
            raise ValueError("PLATFORM_ID_INVALID")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("PLATFORM_NAME_REQUIRED")
        if not self.categories or any(category not in CATEGORIES for category in self.categories):
            raise ValueError("PLATFORM_CATEGORIES_INVALID")
        if self.access_mode not in ACCESS_MODES:
            raise ValueError("PLATFORM_ACCESS_MODE_INVALID")
        if self.integration_status not in INTEGRATION_STATUSES:
            raise ValueError("PLATFORM_INTEGRATION_STATUS_INVALID")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool) or self.priority not in (1, 2, 3):
            raise ValueError("PLATFORM_PRIORITY_MUST_BE_1_TO_3")
        for field_name, value in (
            ("homepage_url", self.homepage_url),
            ("api_docs_url", self.api_docs_url),
            ("discovery_url", self.discovery_url),
        ):
            if value is not None and not _is_http_url(value):
                raise ValueError(f"{field_name.upper()}_INVALID")
        if self.homepage_url is None and self.discovery_url is None:
            raise ValueError("PLATFORM_URL_OR_DISCOVERY_URL_REQUIRED")
        if self.integration_status == "api_documented" and (
            self.access_mode != "api" or self.api_docs_url is None
        ):
            raise ValueError("DOCUMENTED_API_REQUIRES_API_MODE_AND_DOCS")


def _is_http_url(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


PLATFORM_REGISTRY: tuple[PlatformSource, ...] = (
    PlatformSource(
        "saramin", "사람인", ("general", "career"),
        "https://www.saramin.co.kr/", "api", "api_documented", 1,
        api_docs_url="https://oapi.saramin.co.kr/guide/job-search",
        notes="채용공고 검색 API 문서 확인. API 키·이용 한도는 운영 설정에서 별도 관리.",
    ),
    PlatformSource(
        "work24", "고용24", ("general", "public_employment", "regional_employment"),
        "https://www.work24.go.kr/", "api", "api_documented", 1,
        api_docs_url="https://www.work24.go.kr/cm/e/a/0110/selectOpenApiIntro.do",
        notes="공식 Open API 안내 확인. 인증·응답 형식·호출 한도는 연동 전에 재검증.",
    ),
    PlatformSource(
        "alio_job", "잡알리오·ALIO", ("public_institution",),
        "https://alio.go.kr/", "web", "candidate_unverified", 1,
        notes="공공기관 채용정보 후보. 공개 API 및 자동 수집 허용 조건은 미확인.",
    ),
    PlatformSource(
        "gojobs", "나라일터", ("civil_service", "public_employment"),
        "https://www.gojobs.go.kr/", "web", "candidate_unverified", 1,
        notes="공직·정부기관 채용 후보. API 및 자동 수집 조건은 미확인.",
    ),
    PlatformSource(
        "cleaneye_jobplus", "클린아이 잡플러스", ("public_institution", "regional_employment"),
        "https://job.cleaneye.go.kr/", "web", "candidate_unverified", 1,
        notes="지방공기업·지방출자출연기관 채용 후보. API 여부는 미확인.",
    ),
    PlatformSource(
        "hibrain", "하이브레인넷", ("university_faculty", "research"),
        "https://www.hibrain.net/", "web", "candidate_unverified", 1,
        notes="교수 초빙·연구원 등 학술 채용 후보. 자동 수집 조건은 미확인.",
    ),
    PlatformSource(
        "jobs_ac_kr", "JOBS.ac.kr (잡스)", ("university_faculty", "research", "global"),
        "https://new.jobs.ac.kr/", "web", "candidate_unverified", 1,
        notes="석·박사 대상 국내외 교수·연구직 중심 채용 플랫폼. 공개 API 및 자동 수집 조건은 미확인.",
    ),
    PlatformSource(
        "university_official_boards", "대학별 공식 채용 게시판",
        ("university_faculty", "university_staff", "research"),
        None, "institution_specific", "manual_registration_required", 1,
        discovery_url="https://www.academyinfo.go.kr/",
        notes="대학알리미는 대학 식별·탐색 보조용이며 채용 원문은 각 대학 공식 게시판에 등록해야 함.",
    ),
    PlatformSource(
        "rndjob", "이공계인력중개센터", ("research", "career"),
        "https://www.rndjob.or.kr/", "web", "candidate_unverified", 2,
        notes="이공계·R&D 채용 보완 후보. API 및 자동 수집 조건은 미확인.",
    ),
    PlatformSource(
        "jobaba", "잡아바", ("regional_employment", "general", "public_employment"),
        "https://job.gg.go.kr/", "api", "api_documented", 2,
        api_docs_url="https://job.gg.go.kr/jobabaApi/apiGuide.do",
        notes="경기도 지역 일자리 후보. API 인증·범위·호출 한도는 별도 관리.",
    ),
    PlatformSource(
        "jobkorea", "잡코리아", ("general", "career"),
        "https://www.jobkorea.co.kr/", "web", "candidate_unverified", 2,
        notes="종합 채용 후보. 공개 검색 API 및 자동 수집 조건은 미확인.",
    ),
    PlatformSource(
        "wanted", "원티드", ("career", "developer"),
        "https://www.wanted.co.kr/", "web", "candidate_unverified", 2,
        notes="경력직·직무 중심 채용 후보. 외부 검색 API 접근 조건은 미확인.",
    ),
    PlatformSource(
        "remember", "리멤버", ("career",),
        "https://career.rememberapp.co.kr/", "web", "candidate_unverified", 2,
        notes="경력직·전문직 채용 후보. 외부 검색 API 접근 조건은 미확인.",
    ),
    PlatformSource(
        "jumpit", "점핏", ("developer", "career"),
        "https://www.jumpit.co.kr/", "web", "candidate_unverified", 2,
        notes="개발자 채용 특화 후보. 자동 수집 조건은 미확인.",
    ),
    PlatformSource(
        "linkedin_jobs", "LinkedIn Jobs", ("global", "career"),
        "https://kr.linkedin.com/jobs", "web", "candidate_unverified", 3,
        notes="글로벌 채용 후보. 일반 검색 API의 접근 권한과 이용 조건은 미확인.",
    ),
)


def list_platforms(
    *,
    categories: Iterable[str] | None = None,
    integration_status: str | None = None,
) -> tuple[PlatformSource, ...]:
    """Return catalog entries matching all supplied filters, preserving registry order."""
    requested_categories = None if categories is None else frozenset(categories)
    if requested_categories is not None and not requested_categories.issubset(CATEGORIES):
        raise ValueError("PLATFORM_FILTER_CATEGORY_INVALID")
    if integration_status is not None and integration_status not in INTEGRATION_STATUSES:
        raise ValueError("PLATFORM_FILTER_STATUS_INVALID")
    return tuple(
        source for source in PLATFORM_REGISTRY
        if (requested_categories is None or requested_categories.intersection(source.categories))
        and (integration_status is None or source.integration_status == integration_status)
    )


def get_platform(platform_id: str) -> PlatformSource:
    """Return one source by stable ID or raise a clear lookup error."""
    for source in PLATFORM_REGISTRY:
        if source.platform_id == platform_id:
            return source
    raise KeyError("PLATFORM_NOT_FOUND")


def select_platforms(categories: Iterable[str]) -> tuple[PlatformSource, ...]:
    """Select sources for normalized intent categories without coupling to Search Matrix."""
    return list_platforms(categories=categories)
