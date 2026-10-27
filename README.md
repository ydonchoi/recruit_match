# recruit_match

**근거 추적을 지원하는 독립형 채용 검색·매칭 파이프라인**

`recruit_match`는 공개 채용공고의 발견, 출처 정보 보존, 근거 기반 공고 분석 및 직무 적합도 평가를 단계적으로 지원합니다. 검색 결과는 발견 후보일 뿐이며, 공식 공고 여부·모집 진행 여부·지원 자격이 자동으로 검증되었다는 뜻은 아닙니다.

> English summary: A standalone, evidence-oriented recruitment search and job-matching pipeline.

## 주요 기능

- 설정 가능한 공개 웹 검색 API 어댑터
- 선택적으로 활성화하는 정책 범위 내 공개 HTML 발견 어댑터
- 검색 쿼리 계획 및 다중 플랫폼 검색 실행
- 출처 추적 정보와 실행 상태 기록
- 선택 공고에 대한 근거 연결형 직무 적합도 평가
- 단위 테스트와 GitHub Actions 검증 워크플로

## 요구 사항

- Python 3.10 이상
- 핵심 파이프라인 실행에는 Python 표준 라이브러리 사용
- 공개 웹 검색을 위한 승인된 검색 API endpoint, API 키, 정확한 호스트 allowlist
- 선택적 HTML 탐색을 위한 검토된 크롤링 설정

## 빠른 시작

저장소를 내려받고 CLI 도움말을 확인합니다.

```bash
git clone https://github.com/ydonchoi/recruit_match.git
cd recruit_match
python run_pipeline.py --help
```

검색 요청 예시:

```bash
python run_pipeline.py \
  --iteration 1 \
  --request "교육행정·연구지원·정책연구 관련 채용공고" \
  --axis "교육행정" \
  --axis "연구지원" \
  --axis "정책연구" \
  --query-limit 10
```

기본 검색 어댑터는 검색 provider를 명시적으로 설정해야 합니다. 설정이 없으면 결과 0건으로 오인하지 않고 실행을 차단 또는 부분 완료 상태로 기록합니다.

## 공개 검색 provider 설정

검색 provider의 HTTPS endpoint, API 키, 정확한 허용 호스트를 환경 변수로 지정합니다. 실제 키를 저장소에 커밋하지 마세요.

```bash
export RECRUIT_MATCH_SEARCH_ENDPOINT="https://your-approved-provider.example/v7/search"
export RECRUIT_MATCH_SEARCH_API_KEY="키를 안전한 방식으로 주입"
export RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS="your-approved-provider.example"
python run_pipeline.py --request "연구지원 채용" --query-limit 10
```

provider 응답은 `webPages.value` 배열에 `url`, `name`, `snippet` 필드를 포함하는 JSON 형식과 호환되어야 합니다. 다른 응답 형식은 provider 전용 파서가 필요합니다.

## 선택적 HTML 발견

HTML 크롤러는 발견 전용이며, 검토된 seed URL·허용 호스트·이용 조건 검토 상태를 명시한 경우에만 활성화됩니다. 크롤링 전에 대상 사이트의 robots 정책, 이용약관, 접근 조건을 확인하세요. 접근 제한을 우회하도록 설계된 기능이 아닙니다.

환경 변수 `RECRUIT_MATCH_CRAWL_CONFIG_JSON`에는 다음과 같은 JSON 배열을 지정할 수 있습니다.

```json
[
  {
    "platform": "KEDI",
    "seed_urls": ["https://www.kedi.re.kr/"],
    "allowed_hosts": ["www.kedi.re.kr", "kedi.re.kr"],
    "terms_reviewed": true,
    "request_delay_seconds": 2,
    "max_links_per_seed": 100
  }
]
```

위 내용은 **설정 형식 예시**일 뿐, 실제 URL·호스트의 적합성이나 이용 조건을 검토했다는 의미가 아닙니다. 담당자가 관련 조건을 검토하기 전에는 `terms_reviewed`를 `true`로 설정하지 마세요. 크롤러는 HTTPS, 호스트 allowlist, robots.txt 및 응답 제한을 적용합니다.

## 실행 단계와 근거 범위

1. **발견:** 설정된 플랫폼에서 공개 공고 후보를 검색합니다.
2. **검증·분석:** 별도로 구성된 검증 서비스와 출처 근거를 활용해 공고 정보를 평가합니다.
3. **적합도 평가:** 선택한 공고를 대상으로 근거 연결형 직무 적합도 평가를 진행합니다.

후속 단계는 필요한 서비스와 근거가 준비되어 있어야 수행할 수 있습니다. URL을 발견했다는 사실만으로 공고의 공식성, 현재 모집 여부 또는 지원 자격이 확인되는 것은 아닙니다.

관련 설계 문서:
- [필수 검색 워크플로](docs/mandatory-search-workflow.md)
- [요건 중심 직무 매칭](docs/requirement-centered-job-matching.md)
- [목표 워크플로 설계](docs/target-workflow-design.md)

## 개인정보 및 데이터 취급

- 검색 요청에 지원자 이름, 연락처, 계정 자격증명 또는 직접 식별·민감 정보를 입력하지 마세요.
- API 키는 환경 변수 또는 적절한 비밀정보 관리 도구로 주입하고 커밋하지 마세요.
- 공개하기 전에 생성된 로그, 데이터, 원본 아티팩트를 직접 점검하세요.
- 로컬 실행 파일과 수집 아티팩트에 운영 정보 또는 채용 관련 정보가 포함될 수 있으므로, 자동 생성되었다는 이유만으로 공개해도 안전하다고 가정하지 마세요.
- `.gitignore`는 일부 로컬 설정·비밀정보 파일의 신규 추적을 방지합니다. 이미 커밋된 파일이나 Git 이력의 내용을 제거하지는 않습니다.

## 개발 및 테스트

로컬에서 검증을 실행합니다.

```bash
python -m compileall -q run_pipeline.py search_engine.py search_orchestrator.py analysis_pipeline.py workflow_session.py interactive_workflow.py adapters tests
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p "test_runtime_integration.py" -v
```

GitHub Actions 워크플로는 컴파일, 단위 테스트, 통합 테스트, CLI 및 fail-closed 동작을 확인합니다. 워크플로 파일이 존재한다는 사실만으로 검증 성공이 보장되지는 않으므로 Actions 실행 결과를 확인하세요.

## 라이선스

이 프로젝트는 MIT License로 배포됩니다. 자세한 내용은 [LICENSE](LICENSE)를 참조하세요.
