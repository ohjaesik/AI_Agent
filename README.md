# AX Delivery Planner

제조기업의 업무 프로세스와 내부·공식 문서를 기반으로 AX 전환 후보를 분석하고, AI Agent PoC 우선순위를 추천하며, Human Review를 거쳐 DOCX 보고서를 생성하는 LangGraph 기반 MVP입니다.

이 프로젝트는 단순 챗봇이 아니라 `회사/문서/업무 프로세스 데이터 → RAG 근거 검색 → 병렬 분석 Agent → Compliance/Regulatory Mapping → Agent Evaluator → Human Review → PoC 계획 → 보고서 생성`까지 이어지는 AX Delivery 기획 자동화 시스템입니다.

---

## 1. What this system does

AX Delivery Planner는 기업이 여러 업무 중 어떤 영역부터 AI Agent PoC를 시작해야 하는지 판단하기 위한 사전 진단 도구입니다.

핵심 목표는 다음과 같습니다.

- 회사명 또는 DB seed 기반으로 회사/부서/시스템/업무 프로세스/문서 정보를 구성한다.
- 내부 문서와 공식 자료를 RAG로 검색해 업무별 근거를 확보한다.
- 업무 반복성, 문서 의존도, 데이터 준비도, 자동화 가능성, ROI, 위험도를 병렬 분석한다.
- AI Agent 후보를 점수화하고 우선순위를 산정한다.
- AI Governance, Compliance Assessment, Regulatory Mapping을 통해 민감/고영향/금지 가능 후보를 분류한다.
- Agent Evaluator와 LLM Critic으로 근거 부족, 낮은 confidence, 규제 정렬 실패를 재검증한다.
- 필요 시 RAG re-query loop를 수행하고, 최종적으로 Human Review interrupt를 거친다.
- 승인된 후보를 기준으로 6주 PoC 계획과 KPI를 만들고 DOCX 보고서를 생성한다.

---

## 2. High-level architecture

```mermaid
flowchart LR
    User[User / IT Planning Team] --> CLI[CLI / FastAPI]
    CLI --> Graph[LangGraph AX Planner Graph]

    subgraph DataLayer[Data Layer]
        PG[(PostgreSQL + pgvector)]
        Docs[Internal / Official Documents]
        Chunks[Document Chunks + Embeddings]
    end

    subgraph Retrieval[RAG & Evidence]
        Retriever[RAG Retriever]
        Evidence[Evidence Items / Used Sources]
    end

    subgraph Analysis[Analysis Agents]
        Process[Process Analyzer]
        Data[Data Readiness]
        Auto[Automation Feasibility]
        ROI[ROI Cost]
        Risk[Risk Governance]
        Compliance[Compliance + Regulatory Mapping]
    end

    subgraph Decision[Decision Layer]
        Ranking[Priority Ranking]
        Evaluator[Agent Evaluator]
        Critic[LLM Critic]
        Replan[Replan / RAG Re-query]
        Review[Human Review]
    end

    subgraph Delivery[Delivery Output]
        PoC[PoC Delivery Planner]
        Report[Report Writer]
        DOCX[DOCX Generator]
    end

    PG --> Retriever
    Docs --> Chunks --> Retriever
    Retriever --> Evidence
    Evidence --> Analysis
    Graph --> Analysis
    Analysis --> Ranking --> Evaluator --> Critic
    Critic -->|insufficient evidence| Replan --> Retriever
    Critic -->|ready| Review --> PoC --> Report --> DOCX
```

---

## 3. LangGraph agent flow

실제 실행 그래프는 `app/graph/workflow.py`에 정의되어 있습니다.

```mermaid
flowchart TD
    START([START]) --> Load[load_project_data]
    Load --> Retrieve[retrieve_context]

    Retrieve --> Process[process_analyzer]
    Retrieve --> Data[data_readiness]
    Retrieve --> Auto[automation_feasibility]
    Retrieve --> Risk[risk_governance]

    Auto --> ROI[roi_cost]
    Risk --> Compliance[compliance_assessment]

    Process --> Ranking[priority_ranking]
    Data --> Ranking
    ROI --> Ranking
    Compliance --> Ranking

    Ranking --> Evaluator[agent_evaluator]
    Evaluator --> Critic[llm_critic]

    Critic -->|needs more evidence| Replan[agent_replan]
    Replan --> Retrieve

    Critic -->|ready for decision| Human[human_review]
    Human --> PoC[poc_delivery_planner]
    PoC --> Writer[report_writer]
    Writer --> DOCX[docx_generator]
    DOCX --> END([END])
```

### Node responsibilities

| Node | 역할 | 주요 출력 |
|---|---|---|
| `load_project_data` | project/company/process/document/system DB 로드 | `project`, `company_profile`, `business_processes`, `documents` |
| `retrieve_context` | 업무별 RAG context 검색, evidence/used_sources 생성 | `retrieved_contexts`, `evidence_items`, `used_sources` |
| `process_analyzer` | 업무 문제, 병목, 반복성, 문서 의존성 분석 | `process_analysis` |
| `data_readiness` | 데이터 접근성 기준 readiness 분류 | `data_readiness` |
| `automation_feasibility` | 기대효과, 반복성, 구현 가능성, 위험도 기반 자동화 가능성 산정 | `automation_feasibility` |
| `roi_cost` | 시간 절감률, 절감 비용, PoC 비용, ROI 계산 | `roi_cost` |
| `risk_governance` | 보안, 개인정보, 고영향, 법무/안전 리스크 flag 탐지 | `risk_governance` |
| `compliance_assessment` | compliance level과 regulatory mapping 생성 | `compliance_assessment` |
| `priority_ranking` | 후보별 최종 점수와 상태 산정 | `priority_ranking` |
| `agent_evaluator` | evidence coverage, data confidence, compliance alignment 재평가 | `agent_evaluation`, updated `priority_ranking` |
| `llm_critic` | 후보 추천의 근거 충분성/일관성 검토 | `llm_critic`, `replan_request` |
| `agent_replan` | 근거 부족 시 source collection/RAG re-query 준비 | `replan_request` |
| `human_review` | LangGraph interrupt 기반 approve/edit/reject 기록 | `human_review` |
| `poc_delivery_planner` | 6주 PoC 계획, milestone, KPI 생성 | `poc_plan` |
| `report_writer` | 보고서 섹션, 참고문헌, citation validation 생성 | `report_data` |
| `docx_generator` | DOCX 파일 생성 | `report_docx_path` |

---

## 4. State model

그래프는 `AXPlannerState`를 공유 상태로 사용합니다.

```mermaid
flowchart TD
    Input[project_id / company_id / user_request] --> DBData[DB Loaded Data]
    DBData --> RAGState[RAG State]
    RAGState --> AnalysisState[Analysis Results]
    AnalysisState --> DecisionState[Evaluation + Human Review]
    DecisionState --> DeliveryState[PoC Plan + Report]

    DBData -->|project/company/process/document| AnalysisState
    RAGState -->|retrieved_contexts/evidence_items/used_sources| AnalysisState
    AnalysisState -->|priority_ranking/compliance_assessment| DecisionState
    DecisionState -->|approved candidate| DeliveryState
```

주요 state key는 다음과 같습니다.

| Group | Keys |
|---|---|
| Input | `project_id`, `company_id`, `user_request`, `report_requirements` |
| DB data | `project`, `company_profile`, `departments`, `business_processes`, `systems`, `documents` |
| RAG/Evidence | `retrieved_contexts`, `evidence_items`, `used_sources` |
| Analysis | `process_analysis`, `data_readiness`, `automation_feasibility`, `roi_cost`, `risk_governance`, `compliance_assessment`, `priority_ranking`, `agent_evaluation` |
| Replan | `replan_attempts`, `replan_request` |
| Human Review | `human_review` |
| Delivery | `poc_plan`, `report_outline`, `report_data`, `report_docx_path` |
| Observability | `audit_logs`, `errors` |

병렬 분석 node가 같은 state에 동시에 기록하기 때문에 `audit_logs`와 `errors`에는 dedupe reducer가 적용됩니다.

---

## 5. Data and RAG architecture

```mermaid
flowchart TD
    Ingest[Document Ingestion CLI/API] --> Store[documents table]
    Store --> Chunk[Chunking]
    Chunk --> Embed[Embedding]
    Embed --> Vector[(pgvector)]

    Process[Business Processes] --> Query[Process-specific Query]
    Query --> Retriever[RAG Retriever]
    Vector --> Retriever
    Retriever --> Contexts[retrieved_contexts]
    Contexts --> Evidence[evidence_items]
    Evidence --> Sources[used_sources]
```

문서 ingestion은 실제 파일을 DB에 저장하고, chunking/embedding을 통해 RAG 검색 대상으로 만듭니다. 검색 결과는 단순 context로만 쓰지 않고 `evidence_items`, `used_sources`, citation label로 변환되어 보고서와 Agent Evaluator에서 재사용됩니다.

지원 문서 형식:

- `.txt`
- `.md`
- `.pdf`
- `.docx`

---

## 6. Scoring and candidate status

우선순위 산정은 업무 프로세스의 정량/정성 metadata와 분석 node 결과를 결합합니다.

주요 입력:

- `expected_effect`
- `repeatability`
- `document_dependency`
- `data_accessibility`
- `tech_feasibility`
- `risk_score`
- `saving_rate`
- `roi_cost`
- `risk_governance.flags`
- `compliance_assessment.items`
- `evidence_labels`

후보 상태는 다음과 같이 사용합니다.

| Status | 의미 |
|---|---|
| `recommended` | 근거, 데이터, 위험, 규제 검토상 PoC 후보로 추천 가능 |
| `human_review_required` | 민감/고영향/낮은 confidence 등으로 사람 검토 필요 |
| `evidence_insufficient` | 근거·문서·데이터 부족으로 판단 보류 |
| `excluded` | 금지/차단/심각한 compliance risk로 MVP 후보 제외 |

---

## 7. Agent Evaluator

Agent Evaluator는 `priority_ranking` 결과를 그대로 신뢰하지 않고 다음 기준으로 재검증합니다.

```mermaid
flowchart LR
    Candidate[Candidate] --> Evidence[evidence_coverage]
    Candidate --> Data[data_confidence]
    Candidate --> Rationale[rationale_coverage]
    Candidate --> Compliance[compliance_alignment]
    Candidate --> Risk[risk_uncertainty]

    Evidence --> Confidence[confidence_score]
    Data --> Confidence
    Rationale --> Confidence
    Compliance --> Confidence
    Risk --> Confidence

    Confidence --> Status{Status Decision}
    Status --> Recommended[recommended]
    Status --> Review[human_review_required]
    Status --> Insufficient[evidence_insufficient]
    Status --> Excluded[excluded]
```

평가 기준:

- `evidence_coverage`: evidence label, RAG context, evidence item 수 기반
- `data_confidence`: data_accessibility와 context 수 기반
- `rationale_coverage`: score_rationale 필드 충족률
- `compliance_alignment`: blocked/review-required 후보가 추천으로 남아있는지 확인
- `risk_uncertainty`: risk_score와 compliance level 기반 불확실성
- `confidence_score`: 위 항목을 가중합한 종합 confidence

처리 원칙:

- compliance blocked면 `excluded`
- enhanced/sensitive review면 `human_review_required`
- 근거가 없거나 매우 약하면 `evidence_insufficient`
- confidence가 낮거나 issue가 있으면 `human_review_required`

---

## 8. Compliance and regulatory mapping

Compliance Assessment는 내부 업무 후보를 다음 level로 분류합니다.

| Level | 의미 | 처리 |
|---|---|---|
| `standard` | 일반 AX 후보 | 추천 가능 |
| `sensitive_review` | 개인정보·기밀·영업비밀 등 민감 신호 | Human Review 필요 |
| `enhanced_review` | 채용, 금융, 의료, 교육, 핵심 인프라 등 고영향 가능성 | Human Review + 강화 통제 필요 |
| `blocked` | 사회적 점수화, 금지 가능 생체정보, 조작, 범죄예측 등 | 후보 제외 |

Regulatory mapping은 compliance level을 다음 프레임워크와 연결합니다.

| Mapping rule | Framework | 적용 대상 |
|---|---|---|
| `eu_ai_act_prohibited_use` | EU AI Act | 금지/부적절 사용 가능성 |
| `eu_ai_act_high_risk` | EU AI Act | employment, finance, healthcare, education, critical infrastructure 등 |
| `korea_ai_basic_act_high_impact` | Korea AI Basic Act operational proxy | 고영향 AI 가능 영역 |
| `privacy_confidential_data` | Privacy/Security Governance | 개인정보·고객정보·기밀·영업비밀 |
| `standard_assistive_ai` | Korea AI Basic Act / NIST AI RMF / ISO 42001 | 일반 보조형 AI |

출력 필드:

- `regulatory_mappings`
- `regulatory_summary.frameworks`
- `regulatory_summary.risk_categories`
- `regulatory_summary.required_controls`
- `regulatory_summary.obligations`
- `summary.framework_counts`
- `summary.risk_category_counts`

주의: 이 mapping은 법률 자문이 아니라 PoC 기획 단계의 operational compliance screening입니다. 운영 적용 전 공식 법령, 시행령, 고시, 가이드라인과 법무·보안 담당자 검토가 필요합니다.

---

## 9. Human Review and delivery flow

```mermaid
sequenceDiagram
    participant G as LangGraph
    participant E as Agent Evaluator
    participant C as LLM Critic
    participant H as Human Reviewer
    participant P as PoC Planner
    participant R as Report Writer

    G->>E: Evaluate ranked candidates
    E->>C: Send evaluated candidates
    C-->>G: verdict / replan_request
    alt evidence insufficient
        G->>G: agent_replan -> retrieve_context retry
    else ready
        G->>H: interrupt(review_payload)
        H-->>G: approve / edit / reject
        G->>P: build PoC plan
        P->>R: build report data
        R-->>G: DOCX report path
    end
```

Human Review payload에는 top candidates, risk summary, evidence count, source count가 포함됩니다. CLI에서 `--auto-approve`를 사용하면 테스트/데모용으로 자동 승인 흐름을 실행할 수 있습니다.

---

## 10. Report generation

보고서는 `report_writer`와 `docx_generator` 두 단계로 생성됩니다.

1. `report_writer`
   - 분석 결과를 보고서 섹션으로 변환
   - references와 evidence 기반 citation 구성
   - vLLM/Gemma 기반 문단 생성 시도
   - 실패 시 deterministic fallback 사용

2. `docx_generator`
   - `outputs/AX_Delivery_Planner_Report_<project_id>.docx` 생성
   - 표지, 요약, 우선순위, PoC 계획, Human Review, 참고자료 포함

---

## 11. Repository structure

```text
app/
  api/                    FastAPI app, auth, UI endpoints
  agents/                 Agent registry, evaluator, tool guard
  company_bootstrap/      회사명 기반 DB 생성 Supervisor Graph
  compliance/             Compliance assessment, regulatory mapping/policy
  db/                     SQLAlchemy models, CRUD, migrations, seed
  evaluation/             Agent quality eval, gold/holdout builders
  graph/                  LangGraph workflow, state, nodes, worker, replan/review/poc
  ingestion/              File ingestion CLI
  rag/                    Indexer, retriever, embeddings
  sources/                Evidence/source collector
  tools/                  ROI, risk, score, report, DOCX generation utilities

docs/
  AGENT_QUALITY_EVALUATION.md
  REGULATORY_MAPPING.md
  DEPLOYMENT.md
  PRE_UI_ACCEPTANCE_CHECKLIST.md

tests/
  test_agent_quality_eval.py
  test_agent_evaluator.py
  test_external_holdout_builder.py
  test_regulatory_mapping.py
```

---

## 12. Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 13. Environment variables

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
GRAPH_NODE_EXECUTION_MODE=direct
EXTERNAL_WEB_DISCOVERY_ENABLED=false
AGENT_TOOL_SANDBOX_MODE=direct
```

`APP_API_KEY`를 설정하면 보호 API는 `X-API-Key` 헤더가 필요합니다. `APP_JWT_SECRET`을 설정하면 `Authorization: Bearer <token>` 방식도 사용할 수 있습니다.

---

## 14. DB initialization

```bash
python -m app.db.init_pgvector
python -m app.db.create_tables
python -m app.db.migrate_operational_hardening
```

Seed 데이터가 필요하면 다음을 실행합니다.

```bash
python -m app.db.seed --reset
```

---

## 15. RAG indexing

```bash
python -m app.rag.indexer --company-id 1 --reset
```

---

## 16. CLI analysis run

자동으로 최신 project/company를 선택합니다.

```bash
python -m app.main --auto-approve --verbose
```

특정 project를 지정합니다.

```bash
python -m app.main --project-id 4 --auto-approve --verbose
```

실행 후 보고서는 다음 위치에 생성됩니다.

```text
outputs/AX_Delivery_Planner_Report_<project_id>.docx
```

---

## 17. Company bootstrap

Bootstrap Supervisor Graph는 공식 URL 또는 OpenDART 기반으로 회사 DB를 구성합니다.

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

Bootstrap은 서비스 레벨 upsert와 DB unique index를 함께 사용합니다. 같은 회사명, 같은 공식 URL, 같은 업무 후보명으로 재실행하면 기존 회사·문서·업무 후보를 재사용/업데이트하고, 문서 chunk는 문서 단위로 재색인합니다.

실행 결과로 `company_id`, `project_id`, `document_ids`, `process_ids`, `chunk_count`, `workflow_mode`, `agent_trace`가 출력됩니다. 이후 바로 분석을 실행할 수 있습니다.

```bash
python -m app.main --project-id <project_id> --auto-approve --verbose
```

---

## 18. Document ingestion

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

문서만 저장하고 색인은 하지 않으려면 다음을 사용합니다.

```bash
python -m app.ingestion.ingest \
  --company-id 1 \
  --file ./sample_docs/memo.txt \
  --no-index
```

---

## 19. FastAPI run

```bash
python -m uvicorn app.api.main:app --reload --port 8001
```

브라우저에서 접속:

```text
http://localhost:8001/ui
```

API Key 사용 시:

```bash
-H "X-API-Key: $APP_API_KEY"
-H "X-User-Role: admin"
```

JWT 토큰 발급:

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

---

## 20. API examples

Health check:

```bash
curl http://localhost:8001/health
```

회사명 기반 DB 생성:

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

문서 업로드 + RAG 색인:

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

RAG 검색 확인:

```bash
curl -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: analyst" \
  "http://localhost:8001/rag/search?company_id=1&query=공식자료%20사업%20제품&top_k=10"
```

RAG 재색인:

```bash
curl -X POST -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: admin" \
  "http://localhost:8001/rag/reindex?company_id=1&reset=true"
```

분석 실행:

```bash
curl -X POST -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: manager" \
  "http://localhost:8001/analysis/run?company_id=1&auto_approve=true"
```

---

## 21. Quality evaluation

### Regression gate

Regression set은 evaluator 정책이 깨졌는지 확인하는 회귀 테스트입니다. 일반화 성능으로 해석하지 않습니다.

```bash
python -m app.evaluation.agent_quality_eval \
  --dataset regression \
  --strict \
  --min-status-accuracy 0.95 \
  --min-review-accuracy 0.95 \
  --min-status-macro-f1 0.95 \
  --min-review-f1 0.95 \
  --json \
  --csv outputs/agent_quality_regression.csv \
  --markdown outputs/agent_quality_regression.md
```

### Holdout v1 gate

Holdout v1은 별도 검증용이지만 synthetic 성격이 있으므로 최종 일반화 성능으로 표현하지 않습니다.

```bash
python -m app.evaluation.agent_quality_eval \
  --dataset holdout \
  --strict \
  --min-status-accuracy 0.85 \
  --min-review-accuracy 0.85 \
  --min-status-macro-f1 0.80 \
  --min-review-f1 0.85 \
  --json \
  --csv outputs/agent_quality_holdout.csv \
  --markdown outputs/agent_quality_holdout.md
```

### External holdout v2

외부 도메인 CSV를 JSONL 평가셋으로 변환해 custom gold path로 평가합니다.

지원 dataset type:

- `online_retail`
- `bank_marketing`
- `credit_default`
- `process_mining`

```bash
python -m app.evaluation.external_holdout_builder \
  --dataset-type online_retail \
  --input data/external/online_retail.csv \
  --case-id-prefix ext-retail \
  --process-id-start 20000 \
  --max-cases 40 \
  --output-jsonl outputs/external_holdout_v2.jsonl
```

여러 데이터셋을 붙일 때는 `--append`를 사용합니다.

```bash
python -m app.evaluation.agent_quality_eval \
  --gold-path outputs/external_holdout_v2.jsonl \
  --strict \
  --min-status-accuracy 0.85 \
  --min-review-accuracy 0.85 \
  --min-status-macro-f1 0.80 \
  --min-review-f1 0.85 \
  --json \
  --csv outputs/agent_quality_external_holdout_v2.csv \
  --markdown outputs/agent_quality_external_holdout_v2.md
```

최근 external holdout v2 기준 결과 예시:

```text
total_cases = 105
status_accuracy = 0.9619
review_gate_accuracy = 1.0000
status_macro_f1 = 0.9565
status_weighted_f1 = 0.9601
review_gate_f1 = 1.0000
```

---

## 22. Tests

전체 테스트:

```bash
pytest
```

주요 테스트:

```bash
pytest tests/test_agent_evaluator.py
pytest tests/test_agent_quality_eval.py
pytest tests/test_external_holdout_builder.py
pytest tests/test_regulatory_mapping.py
```

---

## 23. Deployment

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

자세한 내용은 `docs/DEPLOYMENT.md`를 참고합니다.

---

## 24. Current limitations

- UI는 FastAPI 테스트 UI 수준이며, 운영형 대시보드는 별도 구현이 필요합니다.
- Regulatory mapping은 법률 자문이 아니라 operational proxy입니다.
- 한국 AI 기본법은 운영 전 국가법령정보센터 원문, 시행령, 고시, 가이드라인 기준으로 재확인해야 합니다.
- vLLM/Gemma 보고서 생성은 환경에 따라 fallback 모드로 동작할 수 있습니다.
- External holdout v2는 일반화 검증에 더 유용하지만, 실제 고객사 데이터 기반 평가와는 구분해야 합니다.
