# AX Delivery Planner

> 제조기업의 공식 자료와 내부 문서를 기반으로 AX 전환 후보 업무를 분석하고, AI Agent PoC 우선순위·거버넌스·보고서를 생성하는 LangGraph 기반 Delivery Planning MVP

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agent%20Workflow-1f6feb)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%20%2B%20pgvector-Vector%20DB-4169E1?logo=postgresql&logoColor=white)
![RAG](https://img.shields.io/badge/RAG-Evidence%20Grounded-6f42c1)

AX Delivery Planner는 단순 챗봇이 아니라 **회사 자료 수집 → RAG 근거 검색 → 병렬 분석 Agent → Compliance/Regulatory Mapping → Agent Evaluator → LLM Critic → Human Review → PoC 계획 → DOCX 보고서 생성**까지 이어지는 AX 전환 기획 자동화 시스템입니다.

핵심 의사결정은 deterministic rule과 score 기반으로 처리하고, LLM은 비정형 공식자료 해석, 보조 검토, 보고서 문장화에 제한적으로 사용합니다. 이를 통해 Agentic Workflow의 유연성은 유지하면서도 추천 결과의 재현성, 설명 가능성, 감사 가능성을 확보합니다.

---

## Table of contents

1. [What this system does](#1-what-this-system-does)
2. [System architecture](#2-system-architecture)
3. [Agent workflow](#3-agent-workflow)
4. [Real-data quick start](#4-real-data-quick-start)
5. [Run analysis and generate report](#5-run-analysis-and-generate-report)
6. [LLM quality evaluation](#6-llm-quality-evaluation)
7. [API workflow](#7-api-workflow)
8. [Core components](#8-core-components)
9. [Quality gates](#9-quality-gates)
10. [Repository structure](#10-repository-structure)
11. [Tests](#11-tests)
12. [Deployment](#12-deployment)

---

## 1. What this system does

AX Delivery Planner는 기업이 여러 업무 중 어떤 영역부터 AI Agent PoC를 시작해야 하는지 판단하기 위한 사전 진단 도구입니다.

| Stage | 역할 | 주요 산출물 |
|---|---|---|
| Company bootstrap | 회사명, 공식 URL, OpenDART 정보로 회사·문서·업무 후보 생성 | `company_id`, `project_id`, `process_ids`, `document_ids` |
| RAG indexing | 공식 자료와 내부 문서를 chunking/embedding 후 pgvector에 저장 | `document_chunks`, embeddings |
| Parallel analysis | 업무별 데이터 준비도, 자동화 가능성, ROI, 위험도, 규제 정합성 분석 | `process_analysis`, `data_readiness`, `roi_cost`, `compliance_assessment` |
| Decision layer | 후보 점수화, Agent Evaluator, LLM Critic, replan/human review 판단 | `priority_ranking`, `agent_evaluation`, `human_review` |
| Delivery output | 승인 후보 기반 6주 PoC 계획과 보고서 생성 | `poc_plan`, `report_data`, `.docx` |
| Evaluation | Agent Evaluator와 LLM 구간 품질 검증 | CSV/Markdown/JSON 평가 리포트 |

### Design principle

| 영역 | 처리 방식 | 이유 |
|---|---|---|
| 점수화·상태 판정 | deterministic rule / score | 재현성, 테스트 가능성, 설명 가능성 확보 |
| RAG 근거 검색 | embedding + pgvector | 후보 업무별 근거와 citation 확보 |
| 공식자료 기반 후보 생성 | LLM 보조 | 비정형 회사 자료에서 업무 후보 추출 |
| LLM Critic | LLM second opinion + calibration | 과도한 추천 또는 근거 부족 후보 보수적 검토 |
| 보고서 작성 | deterministic base + LLM paragraph rewrite | 근거 유지와 문장 품질 균형 |
| 최종 승인 | Human Review | 실제 PoC 적용 전 사람 검토 기록 보존 |

---

## 2. System architecture

```mermaid
flowchart TB
    User[User / IT Planning / AX Consultant]

    subgraph Interface[Interface Layer]
        CLI[CLI: app.main]
        API[FastAPI: app.api.main]
        ReviewUI[Human Review / Test UI]
    end

    subgraph Bootstrap[Company Bootstrap Supervisor]
        Profile[company_profile_agent]
        SourceIngest[source_ingestion_agent]
        Discovery[process_discovery_agent]
    end

    subgraph Data[Operational Data Layer]
        PG[(PostgreSQL)]
        Vector[(pgvector)]
        Docs[Official / Internal Documents]
        Chunks[Document Chunks]
    end

    subgraph RAG[RAG Evidence Layer]
        Embed[OpenAI Embeddings]
        Retriever[Process-specific Retriever]
        Evidence[Evidence Items]
        Sources[Used Sources / Citations]
    end

    subgraph Graph[LangGraph AX Planner]
        Load[load_project_data]
        Retrieve[retrieve_context]
        Analyzer[Parallel Analysis Nodes]
        Ranking[priority_ranking]
        Evaluator[Agent Evaluator]
        Critic[LLM Critic]
        Replan[agent_replan]
        Human[Human Review Interrupt]
        PoC[PoC Delivery Planner]
        Report[Report Writer]
        DOCX[DOCX Generator]
    end

    subgraph Evaluation[Evaluation Layer]
        AgentEval[Agent Quality Eval]
        LLMEval[LLM Quality Eval]
        Reports[CSV / Markdown / JSON Reports]
    end

    User --> CLI
    User --> API
    CLI --> Bootstrap
    API --> Bootstrap
    Bootstrap --> PG
    Bootstrap --> Docs
    Docs --> Chunks --> Embed --> Vector
    PG --> Load
    Vector --> Retriever
    Load --> Retrieve
    Retrieve --> Retriever --> Evidence --> Sources
    Retrieve --> Analyzer --> Ranking --> Evaluator --> Critic
    Critic -->|evidence gap| Replan --> Retrieve
    Critic -->|ready| Human --> PoC --> Report --> DOCX
    ReviewUI --> Human
    Evaluator --> AgentEval
    Discovery --> LLMEval
    Critic --> LLMEval
    Report --> LLMEval
    AgentEval --> Reports
    LLMEval --> Reports
```

### System boundary

| 포함 | 설명 |
|---|---|
| 회사명 기반 공식자료 수집 | 공식 URL, OpenDART 기반 회사 자료 수집 |
| 내부 문서 ingestion | `.txt`, `.md`, `.pdf`, `.docx` 파일 저장 및 RAG 색인 |
| Agent workflow | LangGraph 기반 분석·평가·재계획·보고서 생성 흐름 |
| Governance screening | 민감정보, 고영향, 금지 가능 후보 분류 |
| Human Review | approve/edit/reject 기록 및 보고서 반영 |
| Evaluation gates | Agent Evaluator와 LLM 구간 품질 검증 |

| 제외 또는 제한 | 설명 |
|---|---|
| 법률 자문 | Regulatory mapping은 PoC 단계의 operational screening이며, 운영 전 법무 검토가 필요함 |
| 완성형 운영 UI | 현재 FastAPI test UI/API 중심이며, 별도 프로덕션 대시보드는 범위 밖 |
| LLM 단독 의사결정 | 최종 추천 상태는 rule/score/evaluator/human review로 통제 |

---

## 3. Agent workflow

실제 실행 그래프는 `app/graph/workflow.py`에 정의되어 있습니다.

```mermaid
flowchart TD
    START([START]) --> Load[load_project_data]
    Load --> Retrieve[retrieve_context]

    Retrieve --> Process[process_analyzer]
    Retrieve --> DataReady[data_readiness]
    Retrieve --> Auto[automation_feasibility]
    Retrieve --> Risk[risk_governance]

    Auto --> ROI[roi_cost]
    Risk --> Compliance[compliance_assessment]

    Process --> Rank[priority_ranking]
    DataReady --> Rank
    ROI --> Rank
    Compliance --> Rank

    Rank --> Eval[agent_evaluator]
    Eval --> Critic[llm_critic]

    Critic -->|requires additional evidence| Replan[agent_replan]
    Replan -->|productive source collection| Retrieve
    Replan -->|max attempt / unproductive| Human[human_review]

    Critic -->|ready or review required| Human
    Human --> PoC[poc_delivery_planner]
    PoC --> Writer[report_writer]
    Writer --> Docx[docx_generator]
    Docx --> END([END])
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
| `llm_critic` | 후보 추천의 근거 충분성/일관성 검토 | `llm_critic` |
| `agent_replan` | 근거 부족 시 source collection/RAG re-query 준비 | `replan_request` |
| `human_review` | LangGraph interrupt 기반 approve/edit/reject 기록 | `human_review` |
| `poc_delivery_planner` | 6주 PoC 계획, milestone, KPI 생성 | `poc_plan` |
| `report_writer` | 보고서 섹션, 참고문헌, citation validation 생성 | `report_data` |
| `docx_generator` | DOCX 파일 생성 | `report_docx_path` |

---

## 4. Real-data quick start

이 프로젝트는 seed 데이터 없이도 실제 회사명과 공식 URL을 넣어 실행할 수 있습니다. Seed는 개발용 예시 데이터일 뿐이며, 일반 실행 순서는 **공식자료 bootstrap → 내부 문서 추가 → 분석 실행**입니다.

### 4.1 Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4.2 Configure `.env`

```bash
cp .env.example .env
```

최소 설정 예시:

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
APP_ENV=local
GRAPH_NODE_EXECUTION_MODE=direct
AGENT_TOOL_SANDBOX_MODE=direct
```

### 4.3 Initialize DB

직접 초기화:

```bash
python -m app.db.init_pgvector
python -m app.db.create_tables
python -m app.db.migrate_discovery_metadata
python -m app.db.migrate_operational_hardening
```

또는 bootstrap 실행 시 한 번에 초기화:

```bash
python -m app.company_bootstrap.bootstrap \
  --init-db \
  --company-name "삼성전자" \
  --official-url "https://www.samsung.com/sec/about-us/company-info/"
```

### 4.4 Bootstrap a real company from official sources

공식 URL을 넣으면 회사 profile, 공식 문서, 업무 후보, 분석 project, RAG chunk가 생성됩니다.

```bash
python -m app.company_bootstrap.bootstrap \
  --company-name "삼성전자" \
  --stock-code "005930" \
  --official-url "https://www.samsung.com/sec/about-us/company-info/" \
  --official-url "https://www.samsung.com/sec/about-us/business-area/" \
  --official-url "https://www.samsung.com/sec/sustainability/overview/"
```

실행 결과에서 다음 값을 확인합니다.

```json
{
  "company_id": 1,
  "project_id": 4,
  "document_ids": [1, 2, 3],
  "process_ids": [31, 32, 33],
  "chunk_count": 120
}
```

같은 회사명, 같은 공식 URL, 같은 업무 후보명으로 다시 실행하면 기존 데이터는 재사용/업데이트되고, 문서 chunk는 문서 단위로 재색인됩니다.

### 4.5 Add internal documents

실제 업무 매뉴얼, SOP, 정책 문서, 보고서 등을 추가합니다. 개인 PC 절대경로 대신 repository 기준 상대경로를 사용합니다.

```bash
python -m app.ingestion.ingest \
  --company-id <company_id> \
  --file ./data/private/sop.docx \
  --title "생산 운영 SOP" \
  --department "생산팀" \
  --security-level internal
```

특정 업무 후보와 연결할 수도 있습니다.

```bash
python -m app.ingestion.ingest \
  --company-id <company_id> \
  --process-id <process_id> \
  --file ./data/private/customer_support_policy.pdf \
  --title "고객지원 운영 정책" \
  --department "고객지원팀" \
  --security-level confidential \
  --contains-sensitive-info
```

지원 파일 형식:

- `.txt`
- `.md`
- `.pdf`
- `.docx`

### 4.6 Optional: seed data for development only

Seed는 실제 회사 데이터가 없을 때 로컬 개발용으로만 사용합니다.

```bash
python -m app.db.seed --reset
```

---

## 5. Run analysis and generate report

Bootstrap 결과의 `project_id`를 사용해 분석을 실행합니다.

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --verbose
```

실행 후 기본적으로 workflow state가 저장됩니다.

```text
outputs/workflow_state_real.json
```

보고서는 다음 위치에 생성됩니다.

```text
outputs/AX_Delivery_Planner_Report_<project_id>.docx
```

Human Review를 자동 승인하지 않으려면 `--auto-approve`를 빼고 실행합니다. 이 경우 graph가 interrupt에서 멈추며, 중간 state가 저장됩니다.

```bash
python -m app.main \
  --project-id <project_id> \
  --verbose
```

보고서 metadata를 지정할 수도 있습니다.

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --report-title "제조기업 AX 전환 PoC 우선순위 보고서" \
  --report-author "AX Delivery Team" \
  --report-date "2026-07-09" \
  --report-status reviewed
```

---

## 6. LLM quality evaluation

LLM 품질 평가는 실제 workflow state에서 LLM 관련 결과를 JSONL로 추출한 뒤 실행합니다.

### 6.1 Capture actual LLM outputs

```bash
python -m app.evaluation.capture_llm_quality_cases \
  --state outputs/workflow_state_real.json \
  --output outputs/llm_quality_cases_real.jsonl \
  --case-prefix gemma_real
```

### 6.2 Run LLM quality gate

```bash
python -m app.evaluation.llm_quality_eval \
  --case-path outputs/llm_quality_cases_real.jsonl \
  --strict
```

예시 결과:

```text
total_cases=19
pass_rate=1.0
json_parse_success_rate=1.0
schema_valid_rate=1.0
fallback_free_rate=1.0
quality_gate_passed=True
```

이 평가는 LLM이 생성한 문장이 마음에 드는지 보는 평가가 아니라, 운영 안정성 기준을 확인합니다.

| Target | 검증 기준 |
|---|---|
| `company_process_discovery` | 후보 수, 필수 필드, evidence label, 1~5 점수 범위 |
| `llm_critic` | JSON schema, verdict 유효성, unsafe pass 차단, fallback 여부 |
| `report_writer` | section/paragraph 구조, citation validation, fallback 여부 |

모델 교체 전후 회귀 비교용 baseline을 만들려면 현재 critic verdict를 고정합니다.

```bash
python -m app.evaluation.capture_llm_quality_cases \
  --state outputs/workflow_state_real.json \
  --output outputs/llm_quality_cases_baseline.jsonl \
  --case-prefix baseline_gemma \
  --freeze-current-verdict
```

---

## 7. API workflow

### 7.1 Run FastAPI

```bash
python -m uvicorn app.api.main:app --reload --port 8001
```

Test UI:

```text
http://localhost:8001/ui
```

### 7.2 Bootstrap company by API

```bash
curl -X POST http://localhost:8001/companies/bootstrap \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APP_API_KEY" \
  -d '{
    "company_name": "삼성전자",
    "official_urls": [
      "https://www.samsung.com/sec/about-us/company-info/",
      "https://www.samsung.com/sec/about-us/business-area/"
    ],
    "stock_code": "005930",
    "create_project": true,
    "index": true
  }'
```

### 7.3 Upload internal document by API

```bash
curl -X POST http://localhost:8001/documents/ingest \
  -H "X-API-Key: $APP_API_KEY" \
  -F "company_id=<company_id>" \
  -F "process_id=<process_id>" \
  -F "file=@./data/private/sop.docx" \
  -F "title=생산 운영 SOP" \
  -F "security_level=confidential" \
  -F "allowed_roles=manager,admin" \
  -F "index=true"
```

### 7.4 Check RAG search

```bash
curl -H "X-API-Key: $APP_API_KEY" \
  "http://localhost:8001/rag/search?company_id=<company_id>&query=업무%20절차%20자동화%20근거&top_k=10"
```

### 7.5 Run analysis by API

```bash
curl -X POST -H "X-API-Key: $APP_API_KEY" \
  "http://localhost:8001/analysis/run?project_id=<project_id>&auto_approve=true"
```

---

## 8. Core components

### 8.1 State model

```mermaid
flowchart LR
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

| Group | Keys |
|---|---|
| Input | `project_id`, `company_id`, `user_request`, `report_requirements` |
| DB data | `project`, `company_profile`, `departments`, `business_processes`, `systems`, `documents` |
| RAG/Evidence | `retrieved_contexts`, `evidence_items`, `used_sources` |
| Analysis | `process_analysis`, `data_readiness`, `automation_feasibility`, `roi_cost`, `risk_governance`, `compliance_assessment`, `priority_ranking`, `agent_evaluation` |
| Replan | `replan_attempts`, `replan_request` |
| Human Review | `human_review` |
| Delivery | `poc_plan`, `report_data`, `report_docx_path` |
| Observability | `audit_logs`, `errors` |

### 8.2 RAG and evidence flow

```mermaid
flowchart TD
    File[Official URL / Internal File] --> Document[process_documents]
    Document --> Chunk[chunk text]
    Chunk --> Embedding[embedding]
    Embedding --> Vector[(pgvector)]
    Process[Business Process] --> Query[process-specific query]
    Query --> Search[RAG search]
    Vector --> Search
    Search --> Context[retrieved_contexts]
    Context --> Evidence[evidence_items]
    Evidence --> Citation[report citations]
    Evidence --> Evaluator[Agent Evaluator]
```

### 8.3 Candidate status

| Status | 의미 |
|---|---|
| `recommended` | 근거, 데이터, 위험, 규제 검토상 PoC 후보로 추천 가능 |
| `human_review_required` | 민감/고영향/낮은 confidence 등으로 사람 검토 필요 |
| `evidence_insufficient` | 근거·문서·데이터 부족으로 판단 보류 |
| `excluded` | 금지/차단/심각한 compliance risk로 MVP 후보 제외 |

### 8.4 Agent Evaluator

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

### 8.5 Compliance and regulatory mapping

| Level | 의미 | 처리 |
|---|---|---|
| `standard` | 일반 AX 후보 | 추천 가능 |
| `sensitive_review` | 개인정보·기밀·영업비밀 등 민감 신호 | Human Review 필요 |
| `enhanced_review` | 채용, 금융, 의료, 교육, 핵심 인프라 등 고영향 가능성 | Human Review + 강화 통제 필요 |
| `blocked` | 사회적 점수화, 금지 가능 생체정보, 조작, 범죄예측 등 | 후보 제외 |

Regulatory mapping은 다음 프레임워크와 연결됩니다.

| Mapping rule | Framework | 적용 대상 |
|---|---|---|
| `eu_ai_act_prohibited_use` | EU AI Act | 금지/부적절 사용 가능성 |
| `eu_ai_act_high_risk` | EU AI Act | employment, finance, healthcare, education, critical infrastructure 등 |
| `korea_ai_basic_act_high_impact` | Korea AI Basic Act operational proxy | 고영향 AI 가능 영역 |
| `privacy_confidential_data` | Privacy/Security Governance | 개인정보·고객정보·기밀·영업비밀 |
| `standard_assistive_ai` | Korea AI Basic Act / NIST AI RMF / ISO 42001 | 일반 보조형 AI |

주의: 이 mapping은 법률 자문이 아니라 PoC 기획 단계의 operational compliance screening입니다. 운영 적용 전 공식 법령, 시행령, 고시, 가이드라인과 법무·보안 담당자 검토가 필요합니다.

---

## 9. Quality gates

### 9.1 Agent Evaluator quality gate

Regression set은 evaluator 정책이 깨졌는지 확인하는 회귀 테스트입니다.

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

External holdout v2 예시:

```bash
python -m app.evaluation.external_holdout_builder \
  --dataset-type online_retail \
  --input data/external/online_retail.csv \
  --case-id-prefix ext-retail \
  --process-id-start 20000 \
  --max-cases 40 \
  --output-jsonl outputs/external_holdout_v2.jsonl

python -m app.evaluation.agent_quality_eval \
  --gold-path outputs/external_holdout_v2.jsonl \
  --strict \
  --min-status-accuracy 0.85 \
  --min-review-accuracy 0.85 \
  --min-status-macro-f1 0.80 \
  --min-review-f1 0.85
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

### 9.2 LLM quality gate

LLM quality gate는 실제 workflow 출력에서 다음을 확인합니다.

- JSON 파싱 성공률
- schema 준수율
- fallback-free rate
- evidence label 유효성
- citation validation 통과 여부
- unsafe pass 차단 여부

자세한 실행법은 `docs/LLM_QUALITY_EVALUATION.md`를 참고합니다.

---

## 10. Repository structure

```text
app/
  api/                    FastAPI app, auth, UI endpoints
  agents/                 Agent registry, evaluator, LLM critic, tool guard
  company_bootstrap/      회사명/공식 URL 기반 DB 생성 Supervisor Graph
  compliance/             Compliance assessment, regulatory mapping/policy
  db/                     SQLAlchemy models, CRUD, migrations, seed
  evaluation/             Agent quality eval, LLM quality eval, holdout builders
  graph/                  LangGraph workflow, state, nodes, worker, replan/review/poc
  ingestion/              File ingestion CLI/API service
  rag/                    Indexer, retriever, embeddings
  sources/                Evidence/source collector
  tools/                  ROI, risk, score, report, DOCX generation utilities

docs/
  AGENT_QUALITY_EVALUATION.md
  LLM_QUALITY_EVALUATION.md
  REGULATORY_MAPPING.md
  DEPLOYMENT.md
  PRE_UI_ACCEPTANCE_CHECKLIST.md

tests/
  test_agent_evaluator.py
  test_agent_quality_eval.py
  test_llm_quality_eval.py
  test_capture_llm_quality_cases.py
  test_external_holdout_builder.py
  test_regulatory_mapping.py
```

---

## 11. Tests

전체 테스트:

```bash
pytest
```

주요 테스트:

```bash
pytest tests/test_agent_evaluator.py
pytest tests/test_agent_quality_eval.py
pytest tests/test_llm_quality_eval.py
pytest tests/test_capture_llm_quality_cases.py
pytest tests/test_external_holdout_builder.py
pytest tests/test_regulatory_mapping.py
```

---

## 12. Deployment

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

자세한 내용은 `docs/DEPLOYMENT.md`를 참고합니다.
