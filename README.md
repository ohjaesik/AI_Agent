# AX Delivery Planner

제조기업의 업무 프로세스와 내부 문서를 기반으로 AX 전환 후보를 분석하고, AI Agent PoC 우선순위를 추천하며, DOCX 보고서를 생성하는 LangGraph 기반 MVP입니다.

## 주요 기능

- Bootstrap Supervisor Graph 기반 회사명 + 공식 출처 DB 생성
- AX Analysis Supervisor Graph 기반 병렬 분석
- 회사/부서/시스템/업무 프로세스/문서 DB 로드
- 내부 문서 RAG 색인 및 검색
- 업무 프로세스 분석
- 데이터 준비도, 자동화 가능성, ROI, 보안·거버넌스 위험 분석
- AI Governance 및 Compliance Assessment
- AI Agent 후보 우선순위 추천
- Human Review interrupt 및 자동 승인 실행
- vLLM/Gemma 기반 보고서 문단 작성, 실패 시 deterministic fallback
- DOCX 보고서 생성
- 실제 문서 ingestion CLI/API
- DB unique index 기반 중복 방지 migration
- API Key 및 Bearer JWT 기반 보호 API
- role 기반 문서 접근권한 필터링
- FastAPI 테스트 UI

## 1. 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 환경변수

`.env.example`을 복사해 `.env`를 만듭니다.

```bash
cp .env.example .env
```

예시:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB_NAME
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=google/gemma-2-9b-it
DART_API_KEY=OPTIONAL_OPEN_DART_KEY
APP_API_KEY=OPTIONAL_LOCAL_API_KEY
APP_JWT_SECRET=OPTIONAL_JWT_SECRET
APP_JWT_ALGORITHM=HS256
APP_JWT_EXP_MINUTES=480
APP_ENV=local
```

`DART_API_KEY`를 `.env`에 넣으면 CLI/API 요청에 키를 직접 넘기지 않아도 됩니다. `APP_API_KEY`를 설정하면 보호 API는 `X-API-Key` 헤더가 있어야 호출됩니다. `APP_JWT_SECRET`을 설정하면 `Authorization: Bearer <token>` 방식도 사용할 수 있습니다.

## 3. DB 초기화

```bash
python -m app.db.init_pgvector
python -m app.db.create_tables
python -m app.db.migrate_operational_hardening
```

seed 데이터가 필요하면 다음을 추가로 실행합니다.

```bash
python -m app.db.seed --reset
```

## 4. 기본 RAG 색인

```bash
python -m app.rag.indexer --company-id 1 --reset
```

## 5. CLI 분석 실행

자동으로 최신 project/company를 선택합니다.

```bash
python -m app.main --auto-approve --verbose
```

특정 project를 지정합니다.

```bash
python -m app.main --project-id 4 --auto-approve --verbose
```

실행 후 보고서는 `outputs/AX_Delivery_Planner_Report_<project_id>.docx`에 생성됩니다.

## 6. 회사명 기반 DB 생성

Bootstrap은 다음 Supervisor Graph를 사용합니다.

```text
company_profile_agent
→ source_ingestion_agent
→ process_discovery_agent
```

공식 URL만으로 회사 DB, 부서, 시스템, 업무 후보, 분석 프로젝트, RAG 문서를 생성합니다.

```bash
python -m app.company_bootstrap.bootstrap \
  --company-name "삼성전자" \
  --official-url "https://www.samsung.com/sec/about-us/company-info/"
```

OpenDART API 키가 `.env`의 `DART_API_KEY`에 있으면 별도 인자로 넘기지 않아도 됩니다.

```bash
python -m app.company_bootstrap.bootstrap \
  --company-name "삼성전자" \
  --stock-code "005930" \
  --official-url "https://www.samsung.com/sec/about-us/company-info/" \
  --official-url "https://www.samsung.com/sec/about-us/business-area/" \
  --official-url "https://www.samsung.com/sec/sustainability/overview/"
```

Bootstrap은 서비스 레벨 upsert와 DB unique index를 함께 사용합니다. 같은 회사명, 같은 공식 URL, 같은 업무 후보명으로 재실행하면 기존 회사·문서·업무 후보를 재사용/업데이트하고, 문서 chunk는 문서 단위로 재색인합니다. 실행 결과의 `agent_trace`와 `idempotency` 필드에서 생성/업데이트 여부를 확인할 수 있습니다.

실행 결과로 `company_id`, `project_id`, `document_ids`, `process_ids`, `chunk_count`, `workflow_mode`, `agent_trace`가 출력됩니다. 이후 바로 분석을 실행할 수 있습니다.

```bash
python -m app.main --project-id <project_id> --auto-approve --verbose
```

## 7. 실제 문서 ingestion CLI

지원 형식:

- `.txt`
- `.md`
- `.pdf`
- `.docx`

문서 저장과 RAG 색인을 동시에 수행합니다.

```bash
python -m app.ingestion.ingest \
  --company-id 1 \
  --file ./sample_docs/sop.docx \
  --title "SOP 문서" \
  --department "생산팀" \
  --security-level internal
```

특정 업무 프로세스와 연결하려면 `--process-id`를 사용합니다.

```bash
python -m app.ingestion.ingest \
  --company-id 1 \
  --process-id 31 \
  --file ./sample_docs/sop.pdf
```

문서만 저장하고 색인은 하지 않으려면:

```bash
python -m app.ingestion.ingest \
  --company-id 1 \
  --file ./sample_docs/memo.txt \
  --no-index
```

## 8. FastAPI 실행

```bash
python -m uvicorn app.api.main:app --reload --port 8001
```

브라우저에서 접속:

```text
http://localhost:8001/ui
```

`APP_API_KEY`를 설정한 경우 API 호출에는 다음 헤더를 붙입니다.

```bash
-H "X-API-Key: $APP_API_KEY"
-H "X-User-Role: admin"
```

JWT 토큰을 사용할 경우:

```bash
curl -X POST http://localhost:8001/auth/token \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APP_API_KEY" \
  -d '{"user_id":"ojaesik","role":"admin"}'
```

이후:

```bash
-H "Authorization: Bearer <access_token>"
```

## 9. API 사용 예시

### Health check

```bash
curl http://localhost:8001/health
```

### 회사명 기반 DB 생성

```bash
curl -X POST http://localhost:8001/companies/bootstrap \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: admin" \
  -d '{
    "company_name": "삼성전자",
    "official_urls": ["https://www.samsung.com/sec/about-us/company-info/"],
    "create_project": true,
    "index": true
  }'
```

### 문서 업로드 + RAG 색인

```bash
curl -X POST http://localhost:8001/documents/ingest \
  -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: manager" \
  -F "company_id=1" \
  -F "process_id=31" \
  -F "file=@./sample_docs/sop.docx" \
  -F "security_level=confidential" \
  -F "allowed_roles=manager,admin" \
  -F "index=true"
```

### RAG 검색 확인

```bash
curl -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: analyst" \
  "http://localhost:8001/rag/search?company_id=1&query=공식자료%20사업%20제품&top_k=10"
```

### RAG 재색인

```bash
curl -X POST -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: admin" \
  "http://localhost:8001/rag/reindex?company_id=1&reset=true"
```

### 분석 실행

```bash
curl -X POST -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: manager" \
  "http://localhost:8001/analysis/run?company_id=1&auto_approve=true"
```

## 10. 테스트

```bash
pytest
```

현재 포함된 테스트는 citation label 정규화, API Key/JWT guard, role 기반 문서 접근정책 중심입니다.

## 11. 배포

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

자세한 내용은 `docs/DEPLOYMENT.md`를 참고합니다.

## 12. 추천 결과 평가

gold file 예시:

```json
{
  "relevant_process_ids": [31, 36, 39]
}
```
