# Public Web Search Validation

Public web search는 기본 비활성화 상태다. Replan Loop에서 같은 공식 도메인 자료만으로 근거가 부족할 때, Brave Search 또는 SerpAPI를 보조 출처 탐색에 사용할 수 있다.

## 설정

Brave:

```env
EXTERNAL_WEB_DISCOVERY_ENABLED=true
EXTERNAL_WEB_SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=<SET_VALUE>
EXTERNAL_WEB_MAX_RESULTS=3
```

SerpAPI:

```env
EXTERNAL_WEB_DISCOVERY_ENABLED=true
EXTERNAL_WEB_SEARCH_PROVIDER=serpapi
SERPAPI_API_KEY=<SET_VALUE>
EXTERNAL_WEB_MAX_RESULTS=3
```

## 사전 점검

```bash
python -m app.ops.preflight --json
```

## 실제 검색 smoke test

```bash
python -m app.ops.public_web_search_smoke \
  --company-name "Samsung Electronics" \
  --query-term sustainability \
  --query-term governance \
  --max-results 3 \
  --strict
```

정상 결과는 `ok=true`, `result_count > 0`이다.

## Replan Loop 연동

근거 부족 후보가 있으면 `agent_replan`에서 다음 순서로 동작한다.

1. 기존 공식 URL의 같은 도메인에서 sitemap/link 후보 탐색
2. public web search가 활성화되어 있으면 Brave/SerpAPI 검색
3. 소셜 도메인과 중복 URL 제외
4. 결과 URL을 수집·DB upsert·RAG 색인
5. `retrieve_context` 재실행

결과 위치:

```text
replan_request.source_collection.public_web_search
```

## 제한

- provider/API 품질에 의존한다.
- 기본값은 disabled다.
- 내부 문서 업로드나 인터뷰 메모 생성은 자동화하지 않는다.
- 검색 결과는 보조 출처이며, 최종 PoC 판단은 Human Review를 거친다.
