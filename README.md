<!-- 파일 역할: AX Delivery Planner의 현재 LangGraph/Supervisor-Agent 구조, 실행 방법, 산출물, 과제 대응 내용을 설명한다. -->

# AX Delivery Planner

> 제조기업 AX 전환을 위해 업무 프로세스와 문서를 분석하고, AI Agent 도입 후보·PoC 우선순위·Human Review·Delivery 계획·보고서를 생성하는 Supervisor 기반 Multi-Agent 시스템

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Supervisor%20Agent-1f6feb)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%20%2B%20pgvector-RAG-4169E1?logo=postgresql&logoColor=white)
![Human Review](https://img.shields.io/badge/Human--in--the--loop-Governance-2EAD68)

AX Delivery Planner는 제조기업의 IT기획팀과 AX/DX 추진팀이 여러 부서의 AI Agent 도입 요구를 동일 기준으로 비교하고, 어떤 업무부터 PoC로 추진할지 판단하도록 돕는 **Front Delivery Engineer형 AI Agent 설계 자동화 시스템**이다.

핵심 질문은 “AI Agent를 만들 수 있는가”가 아니라 **“어떤 업무부터 적용해야 효과가 크고 위험이 통제 가능한가”**이다. 이 시스템은 업무자료, SOP, 회의록, 시스템 현황표, 정비 이력, 품질 보고서, 보안 등급표를 바탕으로 후보 Agent를 발굴하고, 데이터 접근성·기대효과·반복성·기술 구현 가능성·현업 수용성·보안/거버넌스 위험을 비교해 PoC 우선순위를 제안한다.

---

## Table of contents

1. [프로젝트 목적](#1-프로젝트-목적)
2. [현재 구현 구조 요약](#2-현재-구현-구조-요약)
3. [Supervisor-Agent Runtime](#3-supervisor-agent-runtime)
4. [Agent stage mapping](#4-agent-stage-mapping)
5. [전체 시스템 아키텍처](#5-전체-시스템-아키텍처)
6. [AI Agent workflow](#6-ai-agent-workflow)
7. [관찰성 및 실행 trace](#7-관찰성-및-실행-trace)
8. [Human-in-the-loop 및 위험 통제](#8-human-in-the-loop-및-위험-통제)
9. [실행 방법](#9-실행-방법)
10. [과제 요구사항 대응](#10-과제-요구사항-대응)
11. [Repository structure](#11-repository-structure)
12. [Tests](#12-tests)

---

## 1. 프로젝트 목적

### 주제 문장

```text
나는 제조 산업의 IT기획팀과 AX 추진 담당자를 위해,
여러 AI Agent 후보 중 어떤 업무부터 PoC로 추진해야 하는지 판단하기 어려운 문제를 해결하는
AX Delivery Planner Agent를 설계한다.
```

### 대상 사용자

| 사용자 | 주요 상황 | AX Delivery Planner 활용 방식 | 산출물 |
|---|---|---|---|
| IT기획팀 | 여러 부서의 AI 도입 요구를 취합해야 함 | 후보 업무를 동일 기준으로 비교 | 후보 목록, 우선순위표 |
| AX/DX 추진팀 | 제한된 예산 안에서 PoC 대상을 선정해야 함 | 기대효과·데이터·위험 기준으로 후보 평가 | MVP 추천 결과 |
| 현업 부서장 | 자기 부서 업무의 적용 가능성을 확인해야 함 | 업무 맥락과 데이터 접근성을 검토 | 점수 수정 의견 |
| 보안·준법 담당자 | 민감정보와 시스템 접근 위험을 검토해야 함 | 위험도와 Human Review 필요 여부 판단 | 보안 승인/반려 기록 |
| 경영진 | PoC 착수 여부와 예산을 승인해야 함 | ROI와 리스크를 요약 보고받음 | PoC 착수 의사결정 |

### 입력과 출력

| 구분 | 내용 |
|---|---|
| 입력 | 업무 설명서, SOP, 회의록, 시스템 현황표, 정비 이력, 품질 보고서, 안전점검표, 보안 등급표, 인건비 가정값 |
| 중간 산출물 | RAG 근거, 업무 진단, 데이터 준비도, 자동화 가능성, 위험/규제 평가, ROI 계산, 우선순위 점수표 |
| 최종 산출물 | AI Agent 후보 랭킹, MVP 추천 결과, Human Review 기록, PoC 계획서, workflow state, DOCX 보고서 |

---

## 2. 현재 구현 구조 요약

현재 코드는 단순 node 연결 그래프가 아니라 **Supervisor가 각 Expert Agent stage에 위임장을 만들고, Expert Agent가 자기 내부 node/tool을 실행한 뒤 package를 handoff하는 구조**로 동작한다.

`app/graph/workflow.py`의 stage 실행 흐름은 다음과 같다.

1. Supervisor 모델을 선택한다.
2. Supervisor LLM이 Expert Agent에게 위임장과 tool policy를 만든다.
3. Expert Agent command LLM이 내부 node 실행 순서를 정한다.
4. runtime은 허용된 내부 node/tool만 실행한다.
5. Expert Agent reflection LLM이 결과 충분성, handoff, iterate, replan, human_review 여부를 판단한다.
6. Supervisor autonomy policy가 extra loop 또는 handoff를 최종 결정한다.
7. Agent package와 handoff trace를 state에 남긴다.

구현상 `Supervisor`는 별도 LangGraph node 하나로 존재하는 것이 아니라, 각 Expert Agent stage가 시작될 때 **Supervisor delegation prompt**로 실행된다. 그 뒤 Expert Agent의 command/reflection prompt가 이어진다.

```text
Supervisor delegation
  -> Expert Agent command prompt
  -> assigned internal nodes/tools 실행
  -> Expert Agent reflection prompt
  -> Supervisor autonomy loop decision
  -> package 생성
  -> downstream Agent handoff
```

`LLM Command Layer`라는 별도 계층은 두지 않는다. `app/agents/agent_llm.py`는 Expert Agent 내부 command/reflection prompt 실행 모듈이고, `app/agents/supervisor_llm.py`는 Supervisor delegation prompt 실행 모듈이다.

---

## 3. Supervisor-Agent Runtime

### 3.1 Supervisor Agent

Supervisor Agent의 역할은 직접 DB/RAG/tool을 실행하는 것이 아니라, 각 Expert Agent stage에 대해 다음 항목을 JSON 위임장으로 생성하는 것이다.

| 항목 | 설명 |
|---|---|
| `supervisor_intent` | 해당 stage에서 달성해야 할 목적 |
| `delegated_to` | 위임받는 Expert Agent ID |
| `node_order` | 우선 실행할 내부 node 순서 |
| `tool_policy` | node별 tool 우선순위와 자율 실행/승인 정책 |
| `human_approval_policy` | Human Review 필요 여부와 승인 gate |
| `iteration_policy` | 추가 loop 허용 조건과 중단 조건 |
| `route_hint` | continue / replan / human_review / stop 경로 힌트 |

Supervisor는 일반 분석, RAG 검색, 점수 계산, LLM Critic, 보고서 초안, DOCX export는 자동 실행을 선호하지만, 고위험/민감정보/심각한 근거 부족/최종 업무 확정은 Human Review 경계로 둔다.

### 3.2 Expert Agent command/reflection

Expert Agent는 Supervisor 위임장을 받은 뒤 두 번의 LLM 판단을 수행한다.

| 단계 | 역할 |
|---|---|
| command prompt | 할당된 내부 node와 tool 목록을 보고 실행 순서, node별 지시, handoff 계획을 JSON으로 생성 |
| reflection prompt | 내부 node 실행 결과를 보고 handoff / iterate / replan / human_review / stop 판단 |

LLM이 timeout되거나 모델 접근 오류가 발생해도 workflow는 멈추지 않는다. 재시도와 모델 상향을 수행하고, 끝내 실패하면 deterministic fallback command/reflection으로 stage를 계속 실행한다.

### 3.3 Model router

`app/agents/model_router.py`는 LLM 호출마다 모델 후보를 비교한다.

| 정책 | 설명 |
|---|---|
| Supervisor | `.env`의 `SUPERVISOR_MODEL_PROVIDER`, `SUPERVISOR_MODEL_NAME`에 지정된 상위 모델을 우선 사용 |
| Expert Agent | OpenAI, Anthropic, vLLM 후보 중 입력량, 예상 출력량, 품질 점수, 속도, context window, 비용을 계산해 선택 |
| timeout retry | Supervisor는 상위 모델을 더 긴 timeout으로 재시도하고, Expert Agent는 더 강한 모델 또는 다른 provider로 상향 |
| trace | 모든 선택 근거와 비용 산식은 `agent_model_decisions`에 기록 |

---

## 4. Agent stage mapping

`app/graph/workflow.py`의 top-level LangGraph node는 Expert Agent stage 단위로 구성된다.

| Stage | 실제 Agent ID | 내부 실행 node | 주요 출력 package |
|---|---|---|---|
| `context_evidence_agent` | `context_evidence_agent` | `load_project_data`, `retrieve_context` | `context_evidence_package` |
| `process_diagnosis_agent` | `process_diagnosis_agent` | `process_analyzer`, `data_readiness`, `automation_feasibility` | `process_diagnosis_package` |
| `governance_compliance_agent` | `governance_compliance_agent` | `risk_governance`, `compliance_assessment` | `governance_package` |
| `business_case_agent` | `business_case_agent` | `roi_cost`, `priority_ranking` | `business_case_package` |
| `evaluation_critic_agent` | `evaluation_critic_agent` | `agent_evaluator`, `llm_critic` | `evaluation_package` |
| `agent_replan` | `evaluation_critic_agent` | `agent_replan` | `replan_request` / updated evaluation |
| `delivery_orchestration_agent` | `delivery_orchestration_agent` | `human_review`, `poc_delivery_planner`, `report_writer`, `docx_generator` | `delivery_package` |

`agent_replan`은 별도 Expert Agent가 아니라 `evaluation_critic_agent`의 재계획 책임으로 실행된다.

---

## 5. 전체 시스템 아키텍처

```mermaid
flowchart TB
    User[User / AX Consultant / Front Delivery Engineer]

    subgraph Interface[Interface Layer]
        CLI[CLI: app.main]
        API[FastAPI API]
        ReviewUI[Human Review UI]
    end

    subgraph Supervisor[Supervisor Delegation]
        Router[Model Router]
        Sup[AX Delivery Supervisor Agent\nDelegation Prompt\nTool Policy\nApproval Policy\nIteration Policy]
    end

    subgraph Agents[Expert Agent Stages]
        C[Context & Evidence Agent\nload_project_data\nretrieve_context]
        P[Process Diagnosis Agent\nprocess_analyzer\ndata_readiness\nautomation_feasibility]
        G[Governance & Compliance Agent\nrisk_governance\ncompliance_assessment]
        B[Business Case Agent\nroi_cost\npriority_ranking]
        E[Evaluation & Critic Agent\nagent_evaluator\nllm_critic]
        R[Agent Replan Task\nagent_replan]
        D[Delivery Orchestration Agent\nhuman_review\npoc_delivery_planner\nreport_writer\ndocx_generator]
    end

    subgraph Data[Data & RAG Layer]
        PG[(PostgreSQL)]
        Vec[(pgvector)]
        Docs[Official / Internal Documents]
        Evidence[Evidence Items / Sources]
    end

    subgraph Governance[Governance & Control]
        RBAC[RBAC]
        Mask[PII / Confidential Masking]
        Allowlist[Tool Allowlist]
        Audit[Audit Log]
        HITL[Human-in-the-loop]
    end

    subgraph Output[Delivery Output]
        Ranking[AI Agent Candidate Ranking]
        MVP[MVP Recommendation]
        Poc[PoC Delivery Plan]
        Trace[Workflow State / Agent Trace]
        Report[DOCX Report]
    end

    User --> CLI
    User --> API
    User --> ReviewUI
    CLI --> Router --> Sup
    API --> Router
    ReviewUI --> HITL

    Sup --> C
    Sup --> P
    Sup --> G
    Sup --> B
    Sup --> E
    Sup --> D

    C --> P
    C --> G
    P --> B
    G --> B
    B --> E
    E -->|evidence gap| R
    R -->|retrieve more evidence| C
    E -->|validated or review needed| D
    D --> Output

    Docs --> PG
    Docs --> Vec
    Vec --> C
    C --> Evidence
    Evidence --> E
    Evidence -.reference.-> B

    RBAC -.control.-> Agents
    Mask -.control.-> Agents
    Allowlist -.control.-> Agents
    Audit -.trace.-> Sup
    HITL -.approval.-> D
```

---

## 6. AI Agent workflow

```mermaid
flowchart TD
    START([Start]) --> C[Context & Evidence Agent]
    C --> P[Process Diagnosis Agent]
    C --> G[Governance & Compliance Agent]
    P --> B[Business Case Agent]
    G --> B
    B --> E[Evaluation & Critic Agent]
    E --> Q{근거 충분 / 검증 통과?}
    Q -->|No| R[Agent Replan Task]
    R -->|재수집 가능| C
    R -->|상한 도달 / 비생산적| D[Delivery Orchestration Agent]
    Q -->|Yes or Human Review needed| D
    D --> F[Finalize Observability]
    F --> END([END])
```

각 Agent stage 내부 실행 단위는 동일하다.

```text
Supervisor delegation
  -> Expert command prompt
  -> assigned tools/internal nodes
  -> Expert reflection prompt
  -> Supervisor loop decision
  -> package / handoff
```

---

## 7. 관찰성 및 실행 trace

실행 결과는 `outputs/workflow_state_real.json`에 저장된다. 이 파일은 보고서/발표에서 프로토타입 증거로 사용할 수 있는 핵심 산출물이다.

| Trace key | 설명 |
|---|---|
| `agent_llm_calls` | Supervisor delegation, Expert command, Expert reflection 호출 성공/실패/retry 기록 |
| `agent_commands` | Expert Agent command/reflection payload |
| `agent_supervisor_delegations` | Supervisor가 각 stage에 만든 위임장, tool policy, approval policy |
| `agent_model_decisions` | 모델 라우터가 선택한 provider/model, workload, 비용 산식, retry 근거 |
| `agent_autonomy_loop_decisions` | Supervisor가 stage별 iterate/handoff/loop_limit/cost_budget을 판단한 기록 |
| `agent_handoffs` | Agent 간 package handoff 기록 |
| `agent_supervisor_steps` | Supervisor가 어떤 stage와 node를 위임했는지 기록 |
| `total_cost_summary` | 전체 LLM 호출의 추정 비용 요약 |
| `*_package` | stage별 handoff package |
| `report_docx_path` | 생성된 DOCX 보고서 경로 |

예시 trace:

```json
{
  "agent_llm_calls": [
    {
      "kind": "supervisor_delegation",
      "agent_id": "ax_delivery_supervisor_agent",
      "stage_name": "business_case_agent",
      "llm_used": true,
      "mode": "supervisor_llm_delegation"
    },
    {
      "kind": "agent_command",
      "agent_id": "business_case_agent",
      "stage_name": "business_case_agent",
      "llm_used": true,
      "mode": "expert_agent_llm_command",
      "node_order": ["roi_cost", "priority_ranking"]
    },
    {
      "kind": "agent_reflection",
      "agent_id": "business_case_agent",
      "stage_name": "business_case_agent",
      "llm_used": true,
      "mode": "expert_agent_llm_reflection",
      "decision": "handoff"
    }
  ]
}
```

---

## 8. Human-in-the-loop 및 위험 통제

AX Delivery Planner는 추천과 근거 생성을 자동화하지만, 고위험 판단과 최종 PoC 착수는 사람의 승인 경계로 둔다.

| 위험 요소 | 통제 방안 |
|---|---|
| 환각 | RAG 근거, citation validation, LLM critic, evaluator |
| 민감정보 노출 | RBAC, 문서 보안등급, PII/기밀 마스킹 |
| Prompt Injection | untrusted content 분리, system prompt 보호, tool allowlist |
| 과도한 Tool 권한 | Agent별 assigned tool만 실행, sandbox/direct mode 구분 |
| 과잉 자동화 | 추천과 실행 분리, Human Review Gate, approval policy |
| 책임 소재 불명확 | Audit Log, reviewer decision, workflow state 저장 |
| 비용/무한 반복 | bounded loop, cost budget, `agent_loop_requests` |

---

## 9. 실행 방법

### MCP interface

기존 `app/agents/registry.py` → `tool_guard.py` → `tool_runtime.py` 경계를
그대로 사용하면서, 업무 단위 MCP tool을 추가로 제공한다. MCP handler가 DB나
LangGraph node를 직접 복제하지 않고 기존 service와 `call_agent_tool()`을
호출하므로 FastAPI/CLI와 실행 trace가 일관된다.

```bash
# 로컬 MCP client (Claude Desktop/Cursor 등)
# MCP_ENABLED=true인 환경에서 실행
python -m app.mcp.server --transport stdio

# 내부/원격 client (기본 endpoint: http://127.0.0.1:8765/mcp)
python -m app.mcp.server --transport streamable-http

# ASGI process manager로 실행할 때
uvicorn app.mcp.http:app --host 127.0.0.1 --port 8765
```

주요 MCP tool은 `search_evidence_tool`, `run_delivery_analysis`,
`get_analysis_status`, `bootstrap_company`, `ingest_document_text`,
`apply_human_review`, `get_report_tool`이다. 분석 workflow는 장시간 실행을
고려해 즉시 `analysis_id`를 반환하고 `get_analysis_status`로 상태를 확인한다.
프로세스 중단으로 실행 중 작업이 끝나지 않으면 DB backend는 이를
`recoverable`로 표시해 실패와 미완료 상태를 구분한다. 재시도는 원래 작업 입력을
다시 구성할 수 있는 별도 worker/queue가 `retry` 계약으로 수행해야 한다.
상태가 `completed` 또는 `human_review`가 되면
`analysis://{analysis_id}/report` resource 또는 `get_report_tool`로 보고서
요약을 읽는다. 작업 큐는 현재 프로세스 내부의 bounded in-memory registry이므로
프로세스 재시작 시 작업 상태가 사라진다. 운영 환경에서는
`MCP_JOB_BACKEND=database`로 durable job metadata 저장을 활성화할 수 있다.
이 모드는 상태/결과를 DB에 보존하지만, 실행 중 프로세스가 중단된 callable을
자동 재개하지는 않으므로 별도 worker/queue 도입이 필요하다.
각 job에는 요청자 user id와 company/project 범위가 함께 저장되며, status/report
조회는 소유자 또는 admin만 허용한다. 따라서 `analysis_id`를 알고 있는 것만으로
다른 사용자의 분석 결과를 읽을 수 없다.

인증은 기존 HTTP API와 같은 JWT/API key 규칙을 사용한다. 개발/내부 환경에서는
`MCP_AUTH_TOKEN`을 설정하고 요청의 `api_key`로 전달할 수 있다. JWT를 사용하는
경우 기존 `APP_JWT_SECRET`과 `/auth/login`에서 발급된 token을 `Authorization:
Bearer ...` header로 전달한다. MCP tool schema에는 인증 credential이나 사용자
role 필드를 노출하지 않으며, Streamable HTTP에서는 `Authorization`, `X-API-Key`,
`X-User-Id`, `X-User-Role` header를 transport context에서 읽는다. stdio client를
외부에 공개할 때는 별도 gateway에서 동일한 인증/사용자 context를 주입해야 한다.
`DART_API_KEY`도 tool argument로 받지 않고 서버 설정에서만 읽는다.
`role`은 문서 보안 등급과 Human Review 권한에 적용된다.

각 Expert Agent에는 `read_scopes`, `write_scopes`, `network_policy`,
`approval_policy`가 선언되어 있다. `call_agent_tool()`은 tool contract뿐
아니라 `call_agent_tool(..., write_scopes=[...])`로 전달된 권한 요구사항도
검사하므로 다른 Agent의 결과 field나 MCP job 영역을 임의로 변경할 수 없다.
write scope는 payload의 magic key가 아니라 runtime 호출의 명시적 인자다. 새로운
write tool을 추가할 때는 registry의 해당 Agent `write_scopes`와 runtime 호출의
`write_scopes`를 함께 갱신하고, 권한 허용/거부 테스트를 추가해야 한다.
`call_agent_tool()`은 명시된 `read_scopes`, `network_policy`,
`approval_requirements`를 Agent registry와 대조한다. `human_required` 또는
`human_review_required` 정책은 `approved_by`, `approved_at`, `decision_id`를
포함한 구조화된 approval record 없이는 실행되지 않는다. 다만 이
guard는 tool이 요청한 정책 계약을 검증하는 경계이며, 모든 외부 network/database
동작을 자동으로 sandboxing하는 기능은 아니므로 실제 network client와 command
tool도 별도의 adapter/sandbox를 사용해야 한다.
공식 URL 수집 adapter는 HTTPS만 허용하고 DNS 해석 결과가 private/link-local
주소인 경우 요청 전에 차단해 SSRF 위험을 줄인다.

Streamable HTTP transport에는 허용 origin, 요청 body 크기, client별 분당
호출 수 제한, `X-Request-ID` 응답 header, 구조화 request log가 적용된다.
기본값은 origin 제한 없음, 분당 120회, body 1 MiB이며 운영 환경에서는
`MCP_ALLOWED_ORIGINS`, `MCP_RATE_LIMIT_PER_MINUTE`, `MCP_MAX_REQUEST_BYTES`를
명시적으로 설정한다.

품질 평가는 두 계층으로 분리한다. CI의 regression/holdout gate는 API key 없이
재현 가능한 deterministic evaluator 정책 회귀를 검증하고, 실제 LLM/API key 기반
online 평가는 별도 환경에서 실행해야 한다. 따라서 CI baseline floor 통과를
실제 LLM 품질 향상으로 해석하지 않으며, online 평가 결과에는 모델/endpoint,
dataset version, latency와 비용을 함께 기록해야 한다.

### 9.1 Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 9.2 Configure `.env`

```bash
cp .env.example .env
```

핵심 설정 그룹:

```env
# Database / RAG
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB_NAME
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
RAG_CHUNK_STRATEGY=semantic

# vLLM OpenAI-compatible endpoint
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=gemma-4-e4b-it

# Model router
MODEL_ROUTER_ENABLED=true
MODEL_ROUTER_ENABLE_VLLM=true
MODEL_ROUTER_ENABLE_OPENAI=true
MODEL_ROUTER_ENABLE_ANTHROPIC=true
SUPERVISOR_MODEL_PROVIDER=openai
SUPERVISOR_MODEL_NAME=gpt-5.6-sol
SUPERVISOR_LLM_ENABLED=true

# Supervisor autonomy
SUPERVISOR_MINIMAL_HUMAN_APPROVAL=true
SUPERVISOR_AUTONOMY_ENABLED=true
SUPERVISOR_AUTONOMY_LEVEL=controlled_high
AGENT_SUPERVISOR_MAX_TOOL_LOOPS=2
AGENT_SUPERVISOR_EXTRA_LOOP_ENABLED=true

# Runtime safety
APP_ENV=local
GRAPH_NODE_EXECUTION_MODE=direct
AGENT_TOOL_SANDBOX_MODE=direct
```

### 9.3 Initialize DB

```bash
python -m app.db.init_pgvector
python -m app.db.create_tables
python -m app.db.migrate_discovery_metadata
python -m app.db.migrate_operational_hardening
python -m app.db.migrate_mcp_jobs
```

### 9.4 Bootstrap company

```bash
python -m app.company_bootstrap.bootstrap \
  --company-name "삼성전자" \
  --stock-code "005930" \
  --official-url "https://www.samsung.com/sec/about-us/company-info/" \
  --official-url "https://www.samsung.com/sec/about-us/business-area/" \
  --official-url "https://www.samsung.com/sec/sustainability/overview/"
```

### 9.5 Add internal documents

```bash
python -m app.ingestion.ingest \
  --company-id <company_id> \
  --file ./data/private/sop.docx \
  --title "생산 운영 SOP" \
  --department "생산팀" \
  --security-level internal
```

### 9.6 Run analysis and report generation

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --verbose
```

출력 위치:

```text
outputs/workflow_state_real.json
outputs/AX_Delivery_Planner_Report_<project_id>.docx
```

보수적으로 한 번의 handoff 중심 흐름만 확인하려면 extra loop를 끈다.

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --disable-agent-extra-loop \
  --verbose
```

장기 목표를 직접 지정할 수도 있다.

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --supervisor-goal "근거 부족 후보까지 자동 보강해 제출 가능한 PoC 보고서 완성" \
  --verbose
```

---

## 10. 과제 요구사항 대응

| 평가 항목 | 배점 | 프로젝트 대응 |
|---|---:|---|
| 도메인 이해도 | 20 | 제조기업 AX 전환 사전진단 업무, 부서별 이해관계자, 보안/규제 구조 분석 |
| 현재 AI 도입 현황 분석 | 15 | FabriX, Brity, Industrial Copilot, 제조 AI, AI 자율제조 사례 기반 병목 정리 |
| Agent 기회 발굴 | 15 | 제조업 AI Agent 후보 10개와 우선순위 기준 설계 |
| MVP Agent 설계 | 25 | AX Delivery Planner 사용자 시나리오, 데이터, 도구, RAG, Human Review, 아키텍처 설계 |
| 리스크 및 평가 설계 | 10 | 환각, 개인정보, 보안, 책임, human approval, evidence/confidence 평가 |
| 프로토타입 또는 데모 | 15 | LangGraph CLI/API 실행, Agent trace, workflow state, DOCX 보고서 생성 |

---

## 11. Repository structure

```text
app/
  agents/
    registry.py              # Expert Agent 계약, 역할, tool_specs
    supervisor_llm.py         # Supervisor delegation prompt, tool policy, approval policy
    agent_llm.py              # Expert Agent command/reflection prompt 실행
    model_router.py           # 모델 비용/성능 라우팅 및 cost trace
    autonomy.py               # Supervisor autonomy, bounded loop decision
    expert_executor.py        # Agent별 assigned tool loop 실행
    handoff.py                # Agent package와 Agent-to-Agent handoff 규칙
    tool_runtime.py           # tool permission check, audit log
  graph/
    workflow.py               # Supervisor delegation + Expert Agent stage LangGraph workflow
    state.py                  # workflow state schema 및 reducer
    nodes.py                  # 분석 internal node 구현
    replan_node.py            # evidence gap 재수집 route
    review_node.py            # Human Review interrupt
    poc_node.py               # PoC delivery plan
  company_bootstrap/          # 회사 공식자료 수집, process discovery
  ingestion/                  # 내부 문서 ingestion/indexing
  evaluation/                 # Agent/LLM quality gate
  tools/                      # report/docx/review helper

docs/
  AGENT_SUPERVISOR_LOOP.md    # Supervisor-Agent handoff 및 loop 구조 설명
  EXPERT_AGENT_RUNTIME.md     # Expert Agent runtime 구조 설명

outputs/
  workflow_state_real.json
  AX_Delivery_Planner_Report_<project_id>.docx
```

---

## 12. Tests

Agent runtime과 evaluator를 검증한다.

```bash
pytest tests/test_agent_runtime.py tests/test_agent_evaluator.py
```

전체 테스트:

```bash
pytest
```

핵심 확인 항목:

```text
agent_llm_calls 존재
agent_llm_calls[*].kind = supervisor_delegation / agent_command / agent_reflection
agent_supervisor_delegations 존재
agent_model_decisions 존재
agent_autonomy_loop_decisions 존재
agent_handoffs 존재
context_evidence_package / business_case_package / delivery_package 존재
각 Agent가 자신에게 할당된 node/tool만 실행
candidate별 recommended / human_review_required / evidence_insufficient 상태 분리
report_docx_path 생성
```
