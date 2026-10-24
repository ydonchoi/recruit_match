# recruit_match

독립형 채용 검색 실행기. 검색 쿼리 생성 엔진은 레거시 저장소에서 선택적으로 이식한 `search_engine.py`이며, 실행 시 `recruitment_matching` 저장소를 import하거나 참조하지 않습니다.

## 실행

Python 3.10+ 필요. 실행기와 검색 엔진은 표준 라이브러리만 사용합니다. 개인별 3단계 세션은 검색·지원자 정보를 프로세스 메모리에서 처리하며, 세션 종료 후 이어서 복구되지 않습니다.

```bash
python run_pipeline.py \
  --iteration 1 \
  --request "교육행정·연구지원·정책연구 관련 현재 채용공고 검색" \
  --axis "교육행정" --axis "연구지원" --axis "정책연구" \
  --query-limit 120
```

검색 조건과 지원자 정보를 대화형으로 입력하고 1~3단계를 진행하려면 다음을 실행합니다. 지원자 자료 입력은 프로세스 메모리에서만 유지되며, 이름·연락처 등 직접 식별 정보는 입력하지 마세요.

```bash
python run_pipeline.py --interactive-session
```

기본 명령은 1단계 검색·수집만 실행하고 공개 공고 원장과 비식별 실행 상태를 기록합니다. 검색어 원문과 검색 축은 저장하지 않습니다. 종료 코드 0은 모든 기준 플랫폼 검색이 성공하고 제한 사항이 없음을 의미합니다. 종료 코드 2는 차단 또는 부분 완료를 의미합니다.

## 플랫폼 어댑터 계약

`adapters/` 아래에 기준 플랫폼마다 Python 모듈을 추가합니다. 각 모듈은 다음을 정의해야 합니다.

- `PLATFORM`: `run_pipeline.py`의 `BASELINE_PLATFORMS`에 있는 정확한 플랫폼 이름
- `search(context)`: 실제 검색을 수행하고 공고 사전(dict) 목록을 반환

각 공고에는 `institution`, `title`, `official_url`가 필요합니다. 지원 상태와 자격요건을 검증된 것으로 표시하려면 해당 상태를 뒷받침하는 근거가 있어야 합니다. 어댑터 누락 및 실패는 검색 결과 0건으로 간주하지 않고 제한 사항으로 기록합니다.

## 선택적 이식 및 출처

`search_engine.py`는 `ydonchoi/recruitment_matching`의 `search_agent/search_matrix.py`와 `search_agent/adaptive_planner.py`를 바탕으로 필요한 검색 행렬·쿼리 계획 계약을 이식한 구현입니다. 실행 시 레거시 체크아웃은 필요하지 않습니다. 이식은 선택적이며 원본 전체 코드의 복제나 완전한 의미 동등성 검증을 뜻하지 않습니다.

## 현재 제한

기본 공개 웹 검색 어댑터(`adapters/public_search.py`)는 검색 결과를 발견 후보로 수집합니다. 공식 채용공고 여부·지원 가능 여부를 검증하지 않습니다. 실제 검색에는 Bing Web Search 호환 JSON 응답을 제공하는 검색 API endpoint, API 키, endpoint 호스트 allowlist가 필요합니다. 플랫폼 사이트 접근 제한을 우회하지 않습니다. 검색 API 설정이 없으면 검색은 차단 또는 부분 완료로 기록됩니다. 2단계의 공식 공고 검증 서비스는 별도로 설정하며, 이 서비스가 없어도 1단계 수집은 실행됩니다.

## 레거시 공개 HTML 어댑터 이식 및 실행 연결

`adapters/public_html_crawl.py`는 `recruitment_matching`의 공개 HTML 발견 어댑터를 이 저장소 계약에 맞춰 이식한 구현입니다. `run_pipeline.py`의 어댑터 로더가 기준 플랫폼별 공개 검색 API 어댑터와, 명시적으로 설정된 HTML 크롤러를 `CompositeAdapter`로 결합합니다. HTML 어댑터는 발견 전용이며 공고 상태·공식성·자격을 검증된 것으로 설정하지 않습니다.

크롤러를 사용하려면 `RECRUIT_MATCH_CRAWL_CONFIG_JSON` 환경변수에 검토한 플랫폼별 seed URL, 허용 호스트, 이용약관 검토 여부를 제공해야 합니다. 이 설정이 없으면 크롤러만 생략하며 검색 API 어댑터는 계속 실행됩니다. 잘못된 설정은 제한 사항으로 기록됩니다. URL이나 호스트는 자동 추측하지 않습니다.

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

위 예시는 설정 형식만 보여주며, 실제 사이트의 URL·robots 정책·약관 적합성을 검증했다는 의미가 아닙니다. 운영 전에 seed URL과 호스트를 확인하고 `terms_reviewed`는 담당자가 이용 조건을 검토한 경우에만 true로 설정하세요. 크롤러는 HTTPS, 호스트 allowlist, robots.txt, 응답 크기 제한, 동일 호스트 리디렉션 제한을 적용합니다. robots.txt 조회 오류는 허용으로 간주하지 않습니다.

수집한 HTML 원본은 SHA-256 기반 파일명으로 `data/source_artifacts/`에 보관하며, 공고 상태·자격은 여전히 `unknown/unverified`입니다. 부분 검색 공급자 오류는 결과 레코드와 실행 로그에 제한 사항으로 기록합니다. 공식 공고 검증과 분석 서비스 연결은 별도 필수 단계이며, HTML 발견 성공만으로 전체 파이프라인 성공을 선언하지 않습니다.

[필수 실행·로그·검증 워크플로](docs/mandatory-search-workflow.md)


## 선택 공고 분석

1단계 목록에서 공고 ID를 확인한 뒤, 원하는 여러 공고만 선택해 2단계 분석을 실행할 수 있습니다.

```bash
python run_pipeline.py --analyze-posting POSTING_ID_1 POSTING_ID_2
```

이 모드는 선택된 공개 공고만 분석하고 결과를 `data/analysis_results.jsonl`에 기록합니다. 검증 서비스가 설정되어 있지 않으면 근거·자격 상태를 차단 또는 보류로 표시합니다.

3단계 단일 공고 평가는 `--interactive-session`에서 진행합니다. 시작 시 입력한 지원자 정보, 근거 발췌, 점수와 추천 결과는 파일에 기록하지 않습니다. 지원 준비 승인을 받은 뒤의 진행 상태도 현재는 세션 메모리에만 유지됩니다. 장기 지원 케이스 보관소는 아직 연결되어 있지 않습니다.

## 통합 실행 계층

- `search_engine.py`: 레거시 검색 행렬·적응형 쿼리 계획을 선택적으로 이식한 로컬 구현
- `search_orchestrator.py`: 쿼리별·플랫폼별 실제 어댑터 실행과 실행 상태 기록
- `analysis_pipeline.py`: 선택된 공개 공고의 정규 분석 단계와 매칭 결과 계산
- `workflow_session.py`, `interactive_workflow.py`: 세션 메모리에서의 다중 공고 선택, 단일 공고 평가, 승인 후 임시 단계 관리
- `analysis_services.py`: 2단계 공고 검증에 필요한 선택적 서비스 연결 파일

개인별 자료는 검색 provider에 전달하지 않으며, 검색 로그에는 원문 대신 무작위 query ref와 집계 정보만 남깁니다. 이메일·전화번호 등 흔한 식별 패턴은 검색 API로 보내기 전 제거합니다. 이름과 기타 민감 정보는 검색 조건에 입력하지 않아야 합니다. 기본 검색에는 검색 API endpoint·키·호스트 allowlist가 필요합니다. 검색은 전체 공고 분석 서비스 없이 실행할 수 있고, 선택 공고의 공식 검증은 별도 서비스가 필요합니다.


## 공개 웹 검색 어댑터 설정

환경 변수로 명시적으로 설정합니다. endpoint는 HTTPS여야 하고, 호스트가 allowlist에 정확히 포함되어야 합니다.

```bash
export RECRUIT_MATCH_SEARCH_ENDPOINT="https://your-approved-search-provider.example/v7/search"
export RECRUIT_MATCH_SEARCH_API_KEY="(키를 안전한 환경변수로 주입)"
export RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS="your-approved-search-provider.example"
python run_pipeline.py --request "교육행정 연구지원 채용" --query-limit 10
```

검색 provider는 `webPages.value` 배열에 `url`, `name`, `snippet`을 포함하는 JSON 응답을 반환해야 합니다. 이 형식과 호환되지 않는 provider는 별도 provider-specific parser가 필요합니다. 키는 저장소에 커밋하지 마세요. 실제 API endpoint와 키는 기본값으로 지정하지 않았습니다.

### 검색 호출 절감 및 수집량 설정

각 계획 검색어는 기준 플랫폼 전체에 대해 실행 기록을 남깁니다. 공개 검색 API 호출은 도메인이 등록된 플랫폼들을 한 요청으로 묶고, 반환 URL의 호스트로 결과를 플랫폼별로 분배합니다. 단일 도메인이 없는 대학·연구기관 채널은 별도 광역 검색 한 번을 공유합니다. 따라서 기본 공개 검색 어댑터에서는 보통 검색어당 최대 2회의 API 요청으로 12개 플랫폼 쌍을 처리합니다. 묶음 요청 실패 시 각 플랫폼별 검색으로 재시도하며 실행 기록에 방식을 남깁니다.

기본 결과 수는 API 요청당 50건이며 `RECRUIT_MATCH_SEARCH_RESULT_COUNT`로 1~50 범위에서 조정할 수 있습니다. 검색 제공자가 실제로 돌려주는 수는 공급자 정책과 검색어에 따라 더 적을 수 있습니다. 검색 결과는 발견 후보이며, 공식 공고·현재 모집 여부·자격요건 검증은 분석 서비스 단계에서 별도로 해야 합니다.
