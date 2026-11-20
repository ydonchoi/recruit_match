# Notion 접근 정책 — Query Data Source 할당량 대응

- 상태: 적용 (에이전트 규칙은 루트 `CLAUDE.md`, 코드는 `adapters/notion_api.py`)
- 근거 확인일: 2026-11-20

## 1. 문제

에이전트가 hosted Notion MCP(`mcp.notion.com`)로 데이터베이스를 읽을 때 `notion-query-data-sources`를 SQL 모드로 반복 호출하면 워크스페이스 공유 할당량에 걸린다.

연결된 MCP 도구 설명(2026-11-20 조회)에 적힌 내용:

| 모드 | 할당량 |
|---|---|
| `view` (저장된 뷰 실행) | 도구 전용 요금제 할당량 없음 |
| `sql` (단일 data source) | Business·Enterprise(Notion AI)는 무제한, 그 외 요금제는 워크스페이스 공유 한도 |
| `rows` (구조화 필터) | 도구 설명에 할당량 언급 없음 — **미확인**, 실제 오류 응답으로 확인 필요 |
| `notion-query-multiple-data-sources` | Business·Enterprise(Notion AI) 전용 |

즉, 할당량은 "Business 전용 Query Data Source 할당량"이 아니라 **비Business 요금제의 SQL 모드 한도**다.

## 2. 제안된 3가지 방식 검토

| 제안 | 판단 | 이유 |
|---|---|---|
| 1) `search` → `fetch` 우회 | **부분 채택** | ID 탐색에는 맞다. 하지만 N개 행을 읽으려고 검색+fetch를 반복하면 호출 수가 1+N으로 늘고, 검색은 별도의 더 낮은 분당 제한이 있다고 알려져 있어(수치는 출처마다 다름) 행 목록 조회의 대체 수단으로는 비효율적이다. |
| 2) 서버 측 필터 구체화 | **채택** | 한 번의 호출로 필요한 행만 받는다. MCP에서는 SQL보다 `view`/`rows` 모드를 먼저 쓴다. |
| 3) 개인 Integration Token + REST API | **채택 (읽기 전용 CLI로 구현)** | REST는 MCP 할당량과 별개이고 평균 3 req/s 제한만 받는다. 단, 현행 API(2025-09-03)는 `POST /v1/data_sources/{id}/query`가 기준이며 `POST /v1/databases/{id}/query`는 구버전(`Notion-Version: 2022-06-28`) 경로다. 구형 로컬 MCP 패키지는 유지보수 상태가 확인되지 않아 채택하지 않았다. |

## 3. 우선순위 (에이전트)

`CLAUDE.md`의 1~7단계를 따른다: 알려진 ID → fetch / 모르는 ID → search 1회 / 행 목록 → `view` / 필요시 `rows` + 정확한 필터 / SQL은 최후 1회 / 오류 시 SQL 재시도 금지 / 반복·대량 조회는 REST CLI.

## 4. REST 어댑터 (`adapters/notion_api.py`)

- **읽기 전용**: `GET /v1/{databases|data_sources|pages}/{id}`, `POST /v1/data_sources/{id}/query`, `POST /v1/databases/{id}/query`만 허용. 그 외 메서드·경로는 요청 전에 거부.
- **fail-closed**: `NOTION_TOKEN`이 없으면 빈 결과가 아니라 오류(종료 코드 2).
- **속도 제한**: 요청 간 최소 간격 1/3초(`NOTION_MAX_RPS`, 최대 3). 429·5xx는 `Retry-After`(최대 60초)를 따르며 최대 3회 재시도.
- **서버 측 필터**: `filter`, `sorts`, `filter_properties`(속성 ID), `page_size`(≤100), `max_pages`(기본 CLI 1, 최대 50). 상한에 걸리면 `truncated: true`.
- **비밀값**: 토큰은 환경 변수로만 읽고 오류 메시지에 넣지 않는다. 호스트는 `api.notion.com` 고정.

### 사용 준비

1. Notion에서 내부 Integration을 만들고 토큰을 발급한다(읽기 권한만 부여 권장).
2. 읽을 데이터베이스 페이지의 `연결(Connections)`에 그 Integration을 추가한다. 추가하지 않으면 `object_not_found`가 난다.
3. 토큰을 환경 변수로 주입한다. 저장소·채팅에 붙여 넣지 않는다.

### 예시

```bash
# 데이터베이스 URL → data source ID 확인
python -m adapters.notion_api get database "https://app.notion.com/p/<db-id>"

# 상태=진행, 마감일 ≥ 2026-11-01, 마감일 오름차순, 50건
python -m adapters.notion_api query --data-source "collection://<ds-id>" \
  --where '상태|status|equals|"진행"' \
  --date-prop 마감일 --since 2026-11-01 \
  --sort 마감일:ascending --page-size 50
```

`--where` 형식은 `속성명|속성타입|연산자|값(JSON)`이며 Notion REST 필터 객체 `{"property": 속성명, 속성타입: {연산자: 값}}`로 변환된다. 복잡한 조건은 `--filter-json`으로 원본 필터 객체를 넘긴다.

## 5. 한계

- 실제 Notion API에 대한 실행 검증은 하지 않았다(테스트는 가짜 transport). 특히 `filter_properties` 쿼리 파라미터 형식(반복 키)은 공식 SDK 방식을 따른 것으로, 실제 응답으로 확인해야 한다.
- MCP 할당량 수치와 `rows` 모드의 할당량 적용 여부는 Notion이 바꿀 수 있다. 오류 응답의 안내를 우선한다.
- 이 저장소 밖(claude.ai 사용자 선호, 스킬)의 Notion 호출 방식은 이 파일로 바뀌지 않는다.
