# recruit_match

독립형 채용 검색 실행기. 검색 쿼리 생성 엔진은 레거시 저장소에서 선택적으로 이식한 `search_engine.py`이며, 실행 시 `recruitment_matching` 저장소를 import하거나 참조하지 않습니다.

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

`search_engine.py`는 `ydonchoi/recruitment_matching`의 `search_agent/search_matrix.py`와 `search_agent/adaptive_planner.py`를 바탕으로 필요한 검색 행렬·쿼리 계획 계약을 이식한 구현입니다. 실행 시 레거시 체크아웃은 필요하지 않습니다. 이식은 선택적이며 원본 전체 코드의 복제나 완전한 의미 동등성 검증을 뜻하지 않습니다.

## 현재 제한

아직 실제 플랫폼 어댑터가 포함되어 있지 않으므로, 어댑터를 추가하기 전 실행은 차단 또는 부분 완료로 기록됩니다. 쿼리 계획 생성만으로 실제 채용 검색이 완료되었다고 보고하지 않습니다.

[필수 실행·로그·검증 워크플로](docs/mandatory-search-workflow.md)
