# CLAUDE.md — 에이전트 작업 규칙

## Notion 접근 규칙 (Query Data Source 할당량 보호)

hosted Notion MCP의 `notion-query-data-sources`는 **SQL 모드**만 비Business 요금제에서 워크스페이스 공유 할당량을 소모한다. 저장된 뷰(`mode: "view"`)는 도구 전용 할당량이 없다(도구 설명 기준). 아래 순서대로, 앞 단계로 해결되면 다음 단계로 가지 않는다.

1. **ID를 이미 알면 바로 `notion-fetch`** 한다. 검색하지 않는다. 확인된 페이지·데이터베이스·`collection://` ID는 대화 안에서 재사용한다.
2. **ID를 모르면 `notion-search` 1회** (`page_size` 5~10, 구체적 키워드, 필요하면 `data_source_url`/`page_url`로 범위 한정) → 결과 ID를 `notion-fetch`.
3. **행 목록이 필요하면 저장된 뷰 URL(`?v=`)로 `mode: "view"`** 를 쓴다. 필요한 필터가 걸린 뷰가 없으면 사용자에게 뷰 추가를 제안한다.
4. 뷰로 안 되면 **`mode: "rows"` + 구조화 필터** 1회: 정확한 속성명·속성 타입(fetch한 스키마에서 복사), 상태값, 날짜 범위(`date_is_within`/`date_is_on_or_after`)를 모두 `filter`에 넣고 `limit`은 필요한 만큼만(≤100).
5. **SQL 모드는 최후 수단**: 1회만, `WHERE`에 필요한 조건 전부 + `LIMIT`, 값은 `?`+`params`로 바인딩. `SELECT *` 후 에이전트가 직접 분류하는 방식 금지. `notion-query-multiple-data-sources`는 Business/Enterprise(Notion AI) 전용이므로 사용하지 않는다.
6. **할당량·429 오류가 나면 SQL을 재시도하지 않는다.** 3번(view) 또는 7번(REST)으로 전환하고, 몇 건을 못 읽었는지 사용자에게 보고한다.
7. **반복·대량 조회는 REST CLI** (`NOTION_TOKEN` 필요, MCP 할당량과 무관, 평균 3 req/s 제한을 클라이언트가 지킴):
   ```bash
   python -m adapters.notion_api query --data-source "collection://<id>" \
     --where '상태|status|equals|"진행"' --date-prop 마감일 --since 2026-11-01 --page-size 50
   ```
   출력의 `truncated: true`는 페이지 상한으로 끊긴 것이며 "전체 결과"로 보고하지 않는다.

금지: 행마다 `notion-search`를 반복하는 N+1 패턴(검색 호출은 별도 분당 제한이 더 낮다), 같은 질의 반복, 결과 없음과 오류·할당량 초과를 같은 "0건"으로 보고하기.

## 데이터 경계

- 이 저장소의 Notion 어댑터는 **읽기 전용**이다. 쓰기 경로를 추가하지 않는다(`docs/notion-access-policy.md` 참조).
- 지원자 자료·개인별 평가는 Notion·파일·로그에 저장하지 않는다. 검색어에 직접 식별 정보를 넣지 않는다.
- `NOTION_TOKEN` 등 비밀값을 커밋·출력·로그하지 않는다.

## 검증

```bash
python -m compileall -q run_pipeline.py search_engine.py search_orchestrator.py analysis_pipeline.py workflow_session.py interactive_workflow.py adapters tests
python -m unittest discover -s tests -v
```
