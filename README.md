# recruit_match

독립형 채용 검색 실행기입니다. 검색 쿼리 생성 엔진은 이 저장소에 포함된 `search_engine.py`이며, 실행에 별도 저장소 체크아웃이 필요하지 않습니다.

## 실행

Python 3.10+ 필요. 실행기와 검색 엔진은 표준 라이브러리만 사용합니다.

```bash
python run_pipeline.py \
  --iteration 1 \
  --request "교육행정·연구지원·정책연구 관련 현재 채용공고 검색" \
  --axis "교육행정" --axis "연구지원" --axis "정책연구" \
  --query-limit 120
```

실행기는 실제 검색 시작 전에 실행 기록을 생성하고, 어댑터가 실행한 결과만 누적 원장과 이벤트 로그에 기록합니다. 종료 코드 0은 12개 기준 플랫폼 어댑터가 모두 성공하고 제한 사항이 없음을 의미합니다. 종료 코드 2는 차단 또는 부분 완료를 의미합니다.

## 플랫폼 어댑터 계약

`adapters/` 아래에 기준 플랫폼마다 Python 모듈을 추가합니다. 각 모듈은 다음을 정의해야 합니다.

- `PLATFORM`: `run_pipeline.py`의 `BASELINE_PLATFORMS`에 있는 정확한 플랫폼 이름
- `search(context)`: 실제 검색을 수행하고 공고 사전(dict) 목록을 반환

각 공고에는 `institution`, `title`, `official_url`가 필요합니다. 지원 상태와 자격요건을 검증된 것으로 표시하려면 해당 상태를 뒷받침하는 근거가 있어야 합니다. 어댑터 누락 및 실패는 검색 결과 0건으로 간주하지 않고 제한 사항으로 기록합니다.

## 선택적 이식 및 출처

`search_engine.py`는 검색 행렬과 쿼리 계획을 생성하는 모듈입니다. 이 저장소의 실행 경로는 해당 모듈의 로컬 구현을 사용합니다.

## 현재 제한

기본 공개 웹 검색 어댑터(`adapters/public_search.py`)를 이식했습니다. 이 어댑터는 검색 API를 통해 발견 결과를 수집하지만, 해당 결과가 공식 채용공고인지 또는 지원 가능한 공고인지는 검증하지 않습니다. 실제 실행에는 Bing Web Search 호환 JSON 응답을 제공하는 검색 API endpoint, API 키, endpoint 호스트 allowlist가 필요합니다. 플랫폼 사이트에 직접 접속하거나 접근 제한을 우회하지 않습니다. API 설정 또는 분석 서비스가 없으면 실행은 차단·부분 완료로 기록되며, 쿼리 계획 생성만으로 실제 검색이 완료되었다고 보고하지 않습니다.

## 레거시 공개 HTML 어댑터 이식 및 실행 연결

`adapters/public_html_crawl.py`는 공개 HTML에서 공고 후보를 발견하는 어댑터입니다. `run_pipeline.py`의 어댑터 로더는 공개 검색 API 어댑터와 명시적으로 설정된 HTML 크롤러를 `CompositeAdapter`로 결합합니다. HTML 어댑터는 발견 전용이며 공고 상태·공식성·자격을 검증된 것으로 설정하지 않습니다.

크롤러를 사용하려면 `RECRUIT_MATCH_CRAWL_CONFIG_JSON` 환경변수에 검토한 플랫폼별 seed URL, 허용 호스트, 이용약관 검토 여부를 제공해야 합니다. URL이나 호스트는 자동 추측하지 않습니다.

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


## 통합 실행 계층

- `search_engine.py`: 레거시 검색 행렬·적응형 쿼리 계획을 선택적으로 이식한 로컬 구현
- `search_orchestrator.py`: 쿼리별·플랫폼별 실제 어댑터 실행과 실행 상태 기록
- `analysis_pipeline.py`: 정규 분석 단계, 근거·자격요건 게이트, 보상 분류, 순위, Top-N, Registry Writer 게이트, 재검증
- `analysis_services.py`: 외부 근거가 필요한 `opportunity_state_resolution`, `assessment_resolution`, `revalidation` 서비스를 `SERVICES` 딕셔너리로 제공하는 선택적 연결 파일

필수 서비스나 플랫폼 어댑터가 없으면 전체 실행은 성공으로 표시되지 않습니다. 플랫폼 어댑터 코드는 포함되어 있지만 검색 API endpoint·키·호스트 allowlist와 분석 서비스가 설정되지 않은 기본 상태에서는 실행이 **차단**되어야 합니다. CI 워크플로는 추가했지만 실제 실행·통과 증거는 별도로 확인해야 합니다.


## 공개 웹 검색 어댑터 설정

환경 변수로 명시적으로 설정합니다. endpoint는 HTTPS여야 하고, 호스트가 allowlist에 정확히 포함되어야 합니다.

```bash
export RECRUIT_MATCH_SEARCH_ENDPOINT="https://your-approved-search-provider.example/v7/search"
export RECRUIT_MATCH_SEARCH_API_KEY="(키를 안전한 환경변수로 주입)"
export RECRUIT_MATCH_SEARCH_ALLOWED_HOSTS="your-approved-search-provider.example"
python run_pipeline.py --request "교육행정 연구지원 채용" --query-limit 10
```

검색 provider는 `webPages.value` 배열에 `url`, `name`, `snippet`을 포함하는 JSON 응답을 반환해야 합니다. 이 형식과 호환되지 않는 provider는 별도 provider-specific parser가 필요합니다. 키는 저장소에 커밋하지 마세요. 실제 API endpoint와 키는 기본값으로 지정하지 않았습니다.
