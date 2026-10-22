"""Self-contained selective port of the legacy Search Matrix query-planning contract.

Ported from ydonchoi/recruitment_matching/search_agent/search_matrix.py and
search_agent/adaptive_planner.py. This module intentionally has no import-time
or runtime dependency on the legacy repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib


@dataclass(frozen=True)
class CandidateEvidence:
    axes: tuple[str, ...]
    locations: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchCombination:
    job_axis: str
    organization_type: str
    query: str
    priority: int
    combination_id: str = ""

    def __post_init__(self) -> None:
        if not self.combination_id:
            identity = f"{self.job_axis}|{self.organization_type}|{self.query}"
            object.__setattr__(self, "combination_id", hashlib.sha256(identity.encode()).hexdigest()[:16])


@dataclass(frozen=True)
class QueryPlan:
    combination: SearchCombination
    prior_utility: float = 0.0
    exploration: bool = True
    axis_prior_utility: float = 0.0


class SearchMatrixPlanner:
    """Deterministic query matrix with candidate axes and broad recall probes."""

    DEFAULT_ORG_TYPES = ("대학", "공공기관", "연구기관", "교육기관", "교육기업")
    LOCATION_TIERS = ("서울", "인천", "경기", "부산", "울산", "경남", "대구", "대전", "세종", "경북", "충청", "그외 지역", "전국")
    MIN_POSTING_DATE = "2024-01-01"

    LEARNED_SEARCH_AXES = (
        "기관단위채용클러스터 × 사업단 × 센터 × 산학협력단 × 행정원/전담직원/프로젝트계약직원",
        "국립대학 × 산학협력 × 연구행정 × 프로젝트계약 × 공공사업운영",
        "국립대학 × 앵커사업 × 지역성장 × 성과관리 × 사업기획",
        "국립대학 × 대학혁신지원 × 프로그램운영 × 정책연구 × 연구지원",
        "국립대학 × 대학재정지원사업 × 데이터분석 × 연구지원 × 프로젝트관리",
        "대학 × 지역성장 × 앵커사업 × 전담직원 × 프로그램운영",
        "대학 × 전략산업 × AX × 정책/사업연구 × 연구지원",
        "대학 × G-LAMP × 연구프로그램운영 × 연구지원",
        "지역발전연구 × 지역정책 × 지리학 × 공간분석 × 정량분석",
        "AI정책 × 과학기술정책 × 공공정책연구 × 데이터분석",
        "교육정책 × 교육서비스 × 프로그램운영 × 연구지원",
        "산학협력 × 연구행정 × 공공연구지원 × 대학",
        "공공교육훈련 × 교육행정 × 교육과정운영 × 사업관리",
    )
    UNIVERSITY_STAFF_RECALL_AXES = (
        "대학 × 교직원/일반직/행정직 × 본부행정 × 학사/학생/연구/기획",
        "대학 × 교직원/일반직/행정직 × 본부행정 × 입학/국제교류/재무",
        "대학 × 직원/전담직원/계약직 × 학사행정 × 교무/수업/학적",
        "대학 × 본부/단과대학/대학원/부속기관 × 행정 × 직원채용",
        "대학 × 직원/전담직원/계약직 × 교수학습/교육혁신 × 프로그램운영",
        "대학 × 직원/전담직원/계약직 × 연구지원 × 연구행정/과제관리",
        "대학 × 직원/전담직원/계약직 × 산학협력단 × 연구/사업행정",
        "대학 × 직원/전담직원/계약직 × 기획/성과관리 × 대학IR/성과분석",
        "대학 × 직원/전담직원/계약직 × 데이터관리 × 통계/SQL/교육데이터",
    )
    SOURCE_CHANNEL_RECALL_AXES = (
        "하이브레인넷 × 정책연구 × 연구원 × 교육·데이터",
        "사람인 × 연구·R&D × 정책연구 × 교육 × 데이터",
        "잡코리아 × 공공기관 × 연구원 × 기획 × 데이터",
        "인크루트 × 공공기관 × 연구행정 × 교육 × 정책",
        "잡알리오 × 연구원 × 일반행정 × 정책 × 데이터",
        "정책브리핑 × 정부·공공기관 × 정책연구 × 임기제 × 연구",
    )
    SEARCH_EXPANSION_AXES = (
        "정책영향분석 × 공공정책 × 통계·마이크로데이터 × 연구지원",
        "공공기관 통합채용 × 경영기획 × 연구지원 × 일반행정",
        "데이터관리 × 공간정보 × 연구지원 × 정책분석 × 공공기관",
        "교육성과평가 × 프로그램효과분석 × 데이터관리 × 교육행정",
        "지역정책 × 주거정책 × 인구·가구 × 공간통계 × 공공연구",
        "공공사업 성과관리 × 사업기획 × 성과지표 × 연구지원",
        "연구데이터 품질관리 × 데이터베이스 × 통계검증 × 연구행정",
        "대학혁신 × 학습성과 × 교육프로그램 × 성과분석 × 연구지원",
        "지역균형발전 × 도시정책 × 공간분석 × 데이터관리 × 연구지원",
        "대학 × 경력개발센터 × 취업지원교육 × 진로프로그램 × 학생지원",
        "대학 × 교수학습지원센터 × 교육혁신 × 교수학습 × 교육성과분석",
        "대학 × ANCHOR/RISE × 사업운영 × 성과관리 × 데이터",
        "대학 × 연구단 × 국가R&D × 연구행정 × 과제관리",
        "교육연구기관 × 평가연구 × 교육통계 × SPSS/데이터분석 × 연구조원",
        "공식첨부파일 × 직무기술서 × 지원서양식 × 필수자격 × 공고검증",
    )

    def __init__(self, organization_types: tuple[str, ...] | None = None):
        self.organization_types = organization_types or self.DEFAULT_ORG_TYPES

    @classmethod
    def location_priority(cls, location: str) -> int:
        try:
            return cls.LOCATION_TIERS.index(location)
        except ValueError:
            return len(cls.LOCATION_TIERS)

    def derive(self, evidence: CandidateEvidence, *, user_query: str = "",
               include_learned_axes: bool = True, limit: int = 120) -> tuple[SearchCombination, ...]:
        axes = tuple(dict.fromkeys((
            *evidence.axes,
            *(self.LEARNED_SEARCH_AXES if include_learned_axes else ()),
            *(self.SEARCH_EXPANSION_AXES if include_learned_axes else ()),
            *(self.SOURCE_CHANNEL_RECALL_AXES if include_learned_axes else ()),
            *(self.UNIVERSITY_STAFF_RECALL_AXES if include_learned_axes else ()),
        )))
        location_targets = tuple(dict.fromkeys(evidence.locations)) if evidence.locations else ("전국",)
        today = date.today().isoformat()
        combinations = []
        for axis in axes:
            for org in self.organization_types:
                for location in location_targets:
                    terms = [axis, org, location, f"공고등록일>={self.MIN_POSTING_DATE}", f"공고등록일<={today}"]
                    terms.extend(evidence.keywords[:2])
                    if user_query.strip():
                        terms.append(user_query.strip())
                    query = " ".join(dict.fromkeys(t for t in terms if t))
                    probe = SearchCombination(axis, org, query, 0)
                    priority = 100000 + self.location_priority(location)
                    combinations.append(SearchCombination(axis, org, query, priority, probe.combination_id))
        ordered = sorted(combinations, key=lambda item: (item.priority, item.job_axis, item.organization_type, item.query))
        return tuple(ordered[:max(1, limit)])


class AdaptiveSearchPlanner:
    """Small, self-contained adaptive-planner port.

    Outcome memory can be supplied as combination-id -> utility. Unknown
    combinations are exploration candidates; no outcome history is fabricated.
    """
    def __init__(self, matrix: SearchMatrixPlanner, outcome_memory: dict[str, float] | None = None):
        self.matrix = matrix
        self.outcome_memory = outcome_memory or {}

    def plan(self, evidence: CandidateEvidence, user_query: str = "", *, limit: int = 120) -> tuple[QueryPlan, ...]:
        combinations = self.matrix.derive(evidence, user_query=user_query, limit=limit)
        plans = [
            QueryPlan(c, self.outcome_memory.get(c.combination_id, 0.0),
                      c.combination_id not in self.outcome_memory, 0.0)
            for c in combinations
        ]
        return tuple(sorted(plans, key=lambda p: (-p.prior_utility, p.combination.priority, p.combination.query)))
