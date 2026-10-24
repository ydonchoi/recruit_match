"""Interactive three-stage workflow with candidate data kept in process memory."""
from __future__ import annotations

from typing import Any, Callable

from job_matching_model import JobRequirement, SourceDocument, retrieve_evidence_on_demand
from run_pipeline import DATA, POSTINGS_FILE, read_jsonl
from workflow_session import (
    APPLICATION_STAGES, ApplicationCase, WorkflowInputError,
    evaluate_single_posting, select_postings,
)


def _read_multiline(prompt: str, input_fn: Callable[[str], str],
                    output_fn: Callable[[str], None]) -> str:
    output_fn(prompt)
    lines = []
    while True:
        line = input_fn("")
        if line == ".":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _parse_requirements(raw: str) -> list[JobRequirement]:
    requirements = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split("|", 5)]
        if len(parts) != 6:
            raise WorkflowInputError("Each requirement needs 6 pipe-separated fields.")
        requirement_id, kind, weight, mandatory, description, keywords = parts
        requirements.append(JobRequirement(
            requirement_id=requirement_id,
            description=description,
            requirement_type=kind.upper(),
            mandatory=mandatory.lower() in {"yes", "y", "true", "필수"},
            weight=float(weight),
            keywords=tuple(value.strip() for value in keywords.split(",") if value.strip()),
        ))
    if not requirements:
        raise WorkflowInputError("Enter at least one requirement.")
    return requirements


def _print_postings(postings: list[dict[str, Any]], output_fn: Callable[[str], None]) -> None:
    for index, row in enumerate(postings, 1):
        output_fn(
            f"{index}. {row.get('institution', '기관 미확인')} | "
            f"{row.get('title', '제목 미확인')} | "
            f"{row.get('location') or '지역 미확인'} | "
            f"{row.get('employment_type') or '고용형태 미확인'} | "
            f"마감 {row.get('deadline_at') or '미확인'} | "
            f"상태 {row.get('application_status', 'unknown')} | "
            f"최근 확인 {row.get('last_checked_at') or '미확인'}\n"
            f"   ID: {row.get('posting_id') or row.get('official_url')}\n"
            f"   URL: {row.get('official_url')}"
        )


def run_interactive_session(run_search: Callable[..., int],
                            run_selected_analysis: Callable[[list[str]], dict[str, Any]],
                            *, input_fn: Callable[[str], str] = input,
                            output_fn: Callable[[str], None] = print) -> int:
    """Run stages 1–3 and an optional in-memory application case."""
    output_fn("검색 조건을 입력하세요. 이름·연락처 등 직접 식별 정보는 검색 조건에 넣지 마세요.")
    search_request = input_fn("희망 직무·기관·지역 등: ").strip()
    if not search_request:
        output_fn("검색 조건이 비어 있어 종료합니다.")
        return 2
    axes_raw = input_fn("검색 축(쉼표 구분, 비우면 기본 축 사용): ").strip()
    axes = [part.strip() for part in axes_raw.split(",") if part.strip()] or [
        "대학", "공공기관", "연구기관", "교육기관", "교육기업",
    ]
    applicant_text = _read_multiline(
        "지원자 경험·기술·학력·자격 정보를 입력하세요. 이름·연락처는 제외하고, 저장하지 않습니다.\n"
        "입력을 마치면 한 줄에 . 을 입력하세요.", input_fn, output_fn,
    )
    if not applicant_text:
        output_fn("3단계 평가를 위해 지원자 정보가 필요합니다.")
        return 2
    try:
        minimum_score = float(input_fn("추천 최소 적합도 점수(0–100, 기본 70): ").strip() or "70")
        if not 0 <= minimum_score <= 100:
            raise ValueError
    except ValueError:
        output_fn("최소 점수는 0부터 100 사이여야 합니다.")
        return 2
    try:
        query_limit = int(input_fn("검색어 수(1–120, 기본 24): ").strip() or "24")
        if not 1 <= query_limit <= 120:
            raise ValueError
    except ValueError:
        output_fn("검색어 수는 1부터 120 사이여야 합니다.")
        return 2

    # Applicant text is deliberately not passed to the search provider.
    search_code = run_search(1, axes, search_request, query_limit)
    postings = read_jsonl(POSTINGS_FILE)
    if not postings:
        output_fn("저장된 공개 공고가 없습니다. 검색 설정을 확인하세요.")
        return search_code or 2
    output_fn("\n1단계: 공고 목록 (여러 공고 선택 가능)")
    _print_postings(postings, output_fn)
    selected_numbers = input_fn("상세 분석할 번호를 쉼표로 입력하세요: ").strip()
    try:
        indices = [int(item.strip()) - 1 for item in selected_numbers.split(",") if item.strip()]
        if any(index < 0 or index >= len(postings) for index in indices):
            raise WorkflowInputError("A selected list number is out of range.")
        selected = select_postings(
            postings,
            [str(postings[index].get("posting_id") or postings[index].get("official_url")) for index in indices],
        )
    except (ValueError, WorkflowInputError):
        output_fn("공고 선택이 올바르지 않습니다.")
        return 2

    output_fn("\n2단계: 선택 공고 상세 분석")
    analysis = run_selected_analysis([
        str(row.get("posting_id") or row.get("official_url")) for row in selected
    ])
    for row in analysis.get("records", []):
        output_fn(
            f"{row.get('institution')} | {row.get('title')} | "
            f"공고 {row.get('application_status', 'unknown')} | "
            f"자격 {row.get('eligibility_gate', 'HOLD')} | "
            f"보상 {row.get('compensation_status', 'UNKNOWN')} "
            f"({row.get('compensation_value', 'UNKNOWN')}) | "
            f"근거 {'확인' if row.get('evidence_validation_passed') else '미확인'} | "
            f"지원 준비 {row.get('writer_gate', 'HOLD')} | "
            f"미확인 {', '.join(row.get('writer_gate_reasons', [])) or '없음'}"
        )
    if analysis.get("status") != "COMPLETED":
        output_fn("상세 검증 서비스가 완료되지 않아 결과를 보류 상태로 표시합니다.")

    output_fn("\n3단계: 적합성을 정밀 평가할 공고 하나를 선택하세요.")
    _print_postings(selected, output_fn)
    try:
        choice = int(input_fn("번호: ").strip()) - 1
        posting = selected[choice]
    except (ValueError, IndexError):
        output_fn("공고 선택이 올바르지 않습니다.")
        return 2
    output_fn(
        "공식 공고의 요건을 한 줄씩 입력하세요. 형식: "
        "ID|TYPE|WEIGHT|MANDATORY|DESCRIPTION|KEYWORDS(comma-separated)\n"
        "TYPE: ELIGIBILITY, CORE_SKILL, EXPERIENCE, TECHNICAL, QUALIFICATION, "
        "DOMAIN_KNOWLEDGE, WORK_CONTEXT. 입력 종료는 ."
    )
    requirements_raw = _read_multiline("요건:", input_fn, output_fn)
    try:
        requirements = _parse_requirements(requirements_raw)
    except (ValueError, WorkflowInputError):
        output_fn("요건 입력을 확인하세요.")
        return 2
    document = SourceDocument(
        document_id="session-candidate-material", text=applicant_text,
        source_type="user-provided-session-material",
    )
    criterion_decisions: dict[str, dict[str, Any]] = {}
    for requirement in requirements:
        snippets = retrieve_evidence_on_demand(requirement, [document])
        output_fn(f"\n{requirement.requirement_id}: {requirement.description}")
        if snippets:
            for snippet in snippets:
                output_fn(f"[{snippet.evidence_id}] {snippet.excerpt}")
        else:
            output_fn("관련 근거를 검색하지 못했습니다. 이는 역량이 없다는 뜻이 아닙니다.")
        score_text = input_fn("검토 점수 0–5 (미평가이면 Enter): ").strip()
        if not score_text:
            criterion_decisions[requirement.requirement_id] = {"status": "UNASSESSED"}
            continue
        try:
            score = float(score_text)
            if not 0 <= score <= 5:
                raise ValueError
        except ValueError:
            output_fn("점수 입력이 올바르지 않습니다.")
            return 2
        refs_raw = input_fn("점수 근거 ID(쉼표 구분, 없으면 Enter): ").strip()
        refs = [item.strip() for item in refs_raw.split(",") if item.strip()]
        status = "ASSESSED" if refs else "UNASSESSED"
        criterion_decisions[requirement.requirement_id] = {
            "score": score if refs else None,
            "status": status,
            "evidence_refs": refs,
            "rationale": input_fn("판정 근거 요약(선택): ").strip(),
        }
    eligibility = input_fn("필수 자격 판정 (PASS/FAIL/HOLD): ").strip().upper()
    if eligibility not in {"PASS", "FAIL", "HOLD"}:
        output_fn("필수 자격 판정이 올바르지 않습니다.")
        return 2
    try:
        result = evaluate_single_posting(
            posting=posting, requirements=requirements,
            candidate_text=applicant_text, eligibility_status=eligibility,
            criterion_decisions=criterion_decisions,
            min_fit_score=minimum_score,
        )
    except (ValueError, TypeError):
        output_fn("평가 입력을 확인하세요. 개인 자료는 저장하지 않았습니다.")
        return 2
    output_fn(
        f"\n평가 상태: {result['evaluation_status']} | "
        f"적합도: {result['fit_score'] if result['fit_score'] is not None else '미평가'} | "
        f"근거 범위: {result['evidence_coverage']:.0%} | "
        f"추천: {result['recommendation']}"
    )
    for row in result["criterion_results"]:
        output_fn(
            f"- {row['requirement_id']}: {row['status']} / "
            f"{row['score'] if row['score'] is not None else '미평가'}"
        )
    if input_fn("이 공고의 지원 준비를 시작할까요? (y/N): ").strip().lower() not in {"y", "yes"}:
        output_fn("지원 준비를 시작하지 않았습니다. 평가 자료는 이 세션 종료 후 폐기됩니다.")
        return search_code

    case = ApplicationCase(str(posting.get("posting_id") or posting.get("official_url")))
    output_fn(f"세션 전용 지원 케이스 시작: {case.status} (저장소에 저장하지 않음)")
    while case.status != "FINAL_RESULT_RECORDED":
        if input_fn("다음 전형 단계로 갱신할까요? (y/N): ").strip().lower() not in {"y", "yes"}:
            break
        next_stage = APPLICATION_STAGES[APPLICATION_STAGES.index(case.status) + 1]
        note = input_fn("확인 메모(선택, 세션 전용): ").strip()
        case.advance(next_stage, user_confirmed=True, note=note)
        output_fn(f"현재 단계: {case.status}")
    output_fn("세션 종료 시 지원자 정보·평가·지원 진행 메모를 폐기합니다.")
    return search_code
