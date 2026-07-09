# AX Delivery Planner

> 관심 산업 기반 AI Agent 도입 전략 및 Delivery 설계 과제를 위한 LangGraph 기반 Supervisor-Agent Delivery Planning MVP

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agent%20Workflow-1f6feb)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%20%2B%20pgvector-Vector%20DB-4169E1?logo=postgresql&logoColor=white)
![RAG](https://img.shields.io/badge/RAG-Evidence%20Grounded-6f42c1)

AX Delivery Planner는 특정 산업·기업의 업무를 분석해 AI Agent 도입 후보를 발굴하고, MVP Agent 선정, Human-in-the-loop, 위험 통제, PoC 계획, 최종 보고서까지 생성하는 **Front Delivery Engineer 관점의 AI Agent 설계 자동화 시스템**입니다.

이 프로젝트의 핵심은 단순히 LLM이 답변하는 챗봇이 아니라, `supervisor_agent`가 하위 Expert Agent에게 업무를 할당하고, 각 Agent가 **자신의 role prompt와 handoff context를 LLM에 넣어 실행 명령을 만든 뒤**, 자신에게 할당된 tool을 실행하고 결과 package를 다음 Agent에게 넘기는 **LLM-driven Agent-to-Agent handoff workflow**입니다.

---

## Table of contents

1. [과제 목적과 프로젝트 대응](#1-과제-목적과-프로젝트-대응)
2. [주제 정의](#2-주제-정의)
3. [최종 Supervisor-Agent 구조](#3-최종-supervisor-agent-구조)
4. [Agent-to-Agent workflow](#4-agent-to-agent-workflow)
5. [과제 요구사항 충족 구조](#5-과제-요구사항-충족-구조)
6. [System architecture](#6-system-architecture)
7. [실행 방법](#7-실행-방법)
8. [산출물](#8-산출물)
9. [평가 기준 대응](#9-평가-기준-대응)
10. [Repository structure](#10-repository-structure)
11. [Tests](#11-tests)

---

## 1. 과제 목적과 프로젝트 대응

### 과제명

**관심 산업 기반 AI Agent 도입 전략 및 Delivery 설계**

### 과제 목적

본 과제는 하나의 관심 산업 또는 업무 분야를 선택하고, 해당 분야의 산업 특성, 현재 AI 도입 현황, 향후 AI Agent 적용 가능성, 구현 기술 요소를 분석하는 것을 목적으로 한다.

학생은 단순히 AI 기술을 조사하는 것이 아니라, 산업 현장의 문제를 이해하고 이를 AI Agent 기반 해결책으로 전환하는 **컨설턴트 / Front Delivery Engineer**의 관점에서 과제를 수행해야 한다.

컨설턴트 / Front Delivery Engineer는 고객, 사용자, 업무 현장의 요구를 이해하고, AI Agent가 실제 업무에 적용될 수 있도록 다음 항목을 설계한다.

- 문제 정의
- 업무 흐름 분석
- AI Agent 후보 발굴
- 데이터·도구·RAG 설계
- Human-in-the-loop 설계
- 위험 관리
- PoC 및 Delivery 계획
- 최종 보고서와 발표자료 산출

### 이 프로젝트의 대응 방식

AX Delivery Planner는 위 과제를 **제조기업 AX 전환 진단**이라는 구체적 주제로 구현한다. 사용자는 AX 기획자, IT/데이터 담당자, 운영/생산 담당자, 경영지원 담당자이며, 목표는 제조기업의 공식자료와 내부 문서를 기반으로 AI Agent 도입 후보를 발굴하고 MVP Agent를 선정하는 것이다.

---

## 2. 주제 정의

과제에서 요구하는 주제 문장 형식은 다음과 같다.

```text
나는 ○○ 산업의 ○○ 사용자를 위해, ○○ 업무 문제를 해결하는 AI Agent를 설계한다.
```

본 프로젝트의 주제 문장은 다음과 같다.

```text
나는 제조 산업의 AX 기획자와 업무 담당자를 위해,
회사 공식자료와 내부 문서를 기반으로 AI Agent 도입 후보를 발굴하고
PoC 우선순위와 Delivery 계획을 자동 생성하는 Supervisor 기반 AI Agent 시스템을 설계한다.
```

### 선택 산업

제조 산업, 특히 대기업 제조사의 AX 전환 기획 업무를 대상으로 한다.

### 대상 사용자

| 사용자 | 역할 | 문제 |
|---|---|---|
| AX 기획 담당자 | AI Agent 후보 발굴, PoC 기획 | 여러 업무 중 우선 도입 대상을 판단하기 어려움 |
| IT/데이터 담당자 | 데이터 접근성, RAG, 시스템 연동 검토 | 업무별 데이터·문서 준비도를 빠르게 파악하기 어려움 |
| 운영/생산 담당자 | 현장 업무 프로세스 개선 | 반복·문서 중심 업무의 자동화 가능성 판단이 어려움 |
| 경영지원/거버넌스 담당자 | 규제, 보안, 승인 검토 | AI Agent 도입 리스크와 Human Review 기준 정리가 필요 |

---

## 3. 최종 Supervisor-Agent 구조

이 시스템은 `supervisor_agent`가 전체 Delivery 흐름을 관리하고, 하위 Expert Agent에게 명령을 할당하는 구조다.

```text
supervisor_agent
  -> Context & Evidence Agent에게 근거 수집 명령
  -> Process Diagnosis Agent에게 업무 진단 명령
  -> Governance & Compliance Agent에게 위험·규제 검토 명령
  -> Business Case Agent에게 ROI·우선순위 산정 명령
  -> Evaluation & Critic Agent에게 추천 결과 검증 명령
  -> Delivery Orchestration Agent에게 Human Review, PoC 계획, 보고서 생성을 명령
```

하위 Agent는 자신에게 할당된 role prompt, task instruction, handoff context, state summary, assigned internal node/tool 목록을 LLM에 입력한다. LLM은 해당 Agent의 실행 명령을 JSON으로 생성하고, runtime은 그 명령에 따라 Agent에게 할당된 node와 tool만 실행한다.

```text
Supervisor가 Agent에게 명령 위임
  -> Agent command prompt를 LLM에 입력
  -> LLM이 node_order / node_commands / handoff_plan 생성
  -> Agent가 자신에게 할당된 internal node 실행
  -> node별 assigned tools 실행
  -> Agent reflection prompt를 LLM에 입력
  -> LLM이 handoff / iterate / replan / human_review / stop 판단
  -> package 생성
  -> 다음 Agent에게 handoff
```

LLM은 두 수준에서 사용된다.

| LLM 사용 위치 | 역할 |
|---|---|
| Agent command prompt | 각 Expert Agent가 자신의 실행 순서, node별 명령, handoff 계획을 생성 |
| Agent reflection prompt | 각 Expert Agent가 실행 결과를 보고 handoff / iterate / replan / human_review / stop 판단 |
| `process_discovery_llm` | 공식자료 기반 업무 후보 생성 |
| `llm_critic` | 추천 후보의 second opinion 검토 |
| `report_writer` | 보고서 문단 생성·정리 |

최종 추천 판단은 LLM 단독이 아니라 assigned tool permission, RAG evidence, score rule, Agent Evaluator, Human Review, loop limit을 통해 통제한다.

---

## 4. Agent-to-Agent workflow

`app/graph/workflow.py`는 기존 세부 node 단위가 아니라 **Expert Agent stage 단위**로 구성된다. 각 Agent stage는 시작 시 LLM command prompt를 호출하고, 내부 tool 실행 후 LLM reflection prompt를 호출한다.

```mermaid
flowchart TD
    S[AX Delivery Supervisor Agent]

    S --> C[Context & Evidence Agent]
    C --> CLLM[Agent LLM Command / Reflection]
    CLLM --> P[Process Diagnosis Agent]
    CLLM --> G[Governance & Compliance Agent]

    P --> B[Business Case Agent]
    G --> B

    B --> E[Evaluation & Critic Agent]
    E -->|근거 부족| R[Agent Replan Task]
    R -->|근거 재수집 가능| C
    R -->|최대 횟수 도달 / 비생산적| D[Delivery Orchestration Agent]

    E -->|검증 완료 / 사람 검토 필요| D
    D --> O[Final DOCX Report]
```

### Agent stage mapping

| Agent stage | 내부 실행 node | 주요 출력 package |
|---|---|---|
| `context_evidence_agent` | `load_project_data`, `retrieve_context` | `context_evidence_package` |
| `process_diagnosis_agent` | `process_analyzer`, `data_readiness`, `automation_feasibility` | `process_diagnosis_package` |
| `governance_compliance_agent` | `risk_governance`, `compliance_assessment` | `governance_package` |
| `business_case_agent` | `roi_cost`, `priority_ranking` | `business_case_package` |
| `evaluation_critic_agent` | `agent_evaluator`, `llm_critic` | `evaluation_package` |
| `agent_replan` | `agent_replan` | updated `evaluation_package` / `replan_request` |
| `delivery_orchestration_agent` | `human_review`, `poc_delivery_planner`, `report_writer`, `docx_generator` | `delivery_package` |

### Agent LLM trace

실행 후 `workflow_state_real.json`에는 Agent prompt가 실제 LLM으로 호출되었는지 남는다.

```json
{
  "agent_llm_calls": [
    {
      "kind": "agent_command",
      "agent_id": "business_case_agent",
      "stage_name": "business_case_agent",
      "llm_used": true,
      "mode": "expert_agent_llm_command",
      "node_order": ["roi_cost", "priority_ranking"],
      "handoff_plan": {
        "next_agent": "evaluation_critic_agent",
        "payload_keys": ["roi_cost", "priority_ranking"]
      }
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

`llm_used=false`이면 LLM endpoint 실패 또는 timeout으로 deterministic fallback이 실행된 것이다. 정상적으로 vLLM/OpenAI-compatible endpoint가 켜져 있으면 `llm_used=true`가 기록된다.

### Handoff trace

Agent 실행 후에는 다음 Agent에게 넘긴 payload도 기록된다.

```json
{
  "agent_supervisor_steps": [
    {
      "supervisor_agent_id": "ax_delivery_supervisor_agent",
      "delegated_to": "business_case_agent",
      "delegated_stage": "business_case_agent",
      "delegated_nodes": ["roi_cost", "priority_ranking"],
      "input_keys": [
        "process_analysis",
        "data_readiness",
        "automation_feasibility",
        "risk_governance",
        "compliance_assessment"
      ],
      "expected_output_keys": ["roi_cost", "priority_ranking"]
    }
  ],
  "agent_handoffs": [
    {
      "from_agent": "business_case_agent",
      "to_agent": "evaluation_critic_agent",
      "source_nodes": ["roi_cost", "priority_ranking"],
      "payload_keys": ["roi_cost", "priority_ranking"]
    }
  ]
}
```

### Loop policy

Agent가 LLM reflection에서 추가 검토가 필요하다고 판단하면 기본적으로 최대 2회까지만 loop를 수행한다.

```text
AGENT_SUPERVISOR_MAX_TOOL_LOOPS=2
```

2회 이후에도 추가 loop가 필요하면 자동으로 무한 반복하지 않는다. 대신 `agent_loop_requests`에 command를 남기고, 사용자가 명시적으로 허용해야 한다.

```bash
python -m app.main --project-id <PROJECT_ID> --auto-approve --allow-agent-extra-loop --verbose
```

허용하지 않으면 현재까지의 결과를 기준으로 다음 Agent에게 handoff한다.

---

## 5. 과제 요구사항 충족 구조

### 5.1 산업 특성 분석

제조기업의 공식자료, OpenDART 기업개황, 내부 문서, 업무 프로세스 정보를 수집한다. 이후 각 업무에 대해 반복성, 문서 의존성, 데이터 접근성, 자동화 가능성, 보안 수준, 규제 리스크를 분석한다.

| 분석 항목 | 구현 위치 | 산출물 |
|---|---|---|
| 산업·기업 정보 | `company_bootstrap` | `company_profile`, `documents` |
| 업무 프로세스 | `process_discovery_agent`, DB | `business_processes` |
| 반복 업무 | `process_analyzer` | `process_analysis` |
| 문서 중심 업무 | RAG / evidence | `retrieved_contexts`, `evidence_items` |
| 데이터 접근성 | `data_readiness` | `data_readiness` |
| 규제·보안 이슈 | `risk_governance`, `compliance_assessment` | `risk_governance`, `compliance_assessment` |

### 5.2 현재 AI 도입 현황 조사

보고서 작성 단계에서 현재 AI 활용 사례, 기업 공식자료, 외부/내부 문서 기반 근거를 section과 reference로 구성한다. LLM은 근거 없는 사례를 임의로 확정하지 않고, citation validation을 거친다.

### 5.3 향후 AI Agent 도입 후보 발굴

업무 후보는 최소 10개 이상 도출할 수 있도록 설계되어 있다. 각 후보는 다음 기준으로 비교된다.

| 비교 기준 | 사용 필드 |
|---|---|
| 대상 사용자 | `target_user` |
| 해결 문제 | `problem` |
| 기대 효과 | `expected_effect`, `saving_rate` |
| 기술 난이도 | `tech_feasibility`, `implementation_cost_score` |
| 위험도 | `risk_score`, `risk_governance` |
| 데이터 접근 가능성 | `data_accessibility`, `data_readiness` |
| 문서 근거 | `evidence_coverage`, `used_sources` |

### 5.4 MVP AI Agent 설계

최종 MVP 후보는 `priority_ranking`과 Human Review를 거쳐 선정된다. 보고서에는 다음 항목이 포함된다.

| 설계 항목 | 산출 위치 |
|---|---|
| Agent 이름 | `candidate_agent_name`, `mvp_agent` |
| 대상 사용자 | `target_user` |
| 사용 시나리오 | `poc_plan`, `report_data` |
| 입력과 출력 | `poc_plan.mvp_agent`, `report_data.sections` |
| 업무 흐름 | `poc_plan.milestones`, architecture diagram |
| 필요한 데이터 | `data_readiness`, `context_evidence_package` |
| 외부 도구/API | RAG, pgvector, OpenDART, optional web discovery |
| RAG 활용 여부 | `retrieved_contexts`, `evidence_items` |
| Human-in-the-loop | `human_review`, `review_node` |
| 평가 지표 | `poc_plan.kpis`, `agent_evaluation` |
| 위험 요소 및 통제 방안 | `risk_governance`, `compliance_assessment` |

### 5.5 프로토타입 또는 데모

이 프로젝트는 실제 실행 가능한 CLI/API 기반 프로토타입이다. 구현이 어려운 부분은 화면 예시 대신 다음 자료로 대체 가능하다.

- Agent-to-Agent workflow diagram
- Agent LLM command/reflection trace
- workflow state JSON
- 입력·출력 샘플
- Prompt / role contract
- Tool 목록
- 실패 시나리오와 replan route
- Human Review interrupt payload
- DOCX 보고서 산출물

---

## 6. System architecture

```mermaid
flowchart TB
    User[User / AX Consultant / Front Delivery Engineer]

    subgraph Interface[Interface Layer]
        CLI[CLI: app.main]
        API[FastAPI API]
        Review[Human Review]
    end

    subgraph Supervisor[Supervisor Layer]
        Sup[AX Delivery Supervisor Agent]
    end

    subgraph Agents[Expert Agent Stages]
        C[Context & Evidence Agent]
        P[Process Diagnosis Agent]
        G[Governance & Compliance Agent]
        B[Business Case Agent]
        E[Evaluation & Critic Agent]
        D[Delivery Orchestration Agent]
    end

    subgraph LLM[LLM Command Layer]
        Cmd[Agent Command Prompt]
        Ref[Agent Reflection Prompt]
    end

    subgraph Data[Data & RAG Layer]
        PG[(PostgreSQL)]
        Vec[(pgvector)]
        Docs[Official / Internal Documents]
        Evidence[Evidence Items / Sources]
    end

    subgraph Output[Delivery Output]
        Ranking[AI Agent Candidate Ranking]
        PoC[6-week PoC Plan]
        Report[DOCX Report]
    end

    User --> CLI
    User --> API
    CLI --> Sup
    API --> Sup
    Sup --> C
    C --> Cmd
    Cmd --> Ref
    Ref --> P
    Ref --> G
    P --> B
    G --> B
    B --> E
    E --> D
    D --> Review
    D --> PoC
    D --> Report
    Docs --> PG
    Docs --> Vec
    Vec --> C
    C --> Evidence
    Evidence --> P
    Evidence --> G
    Evidence --> E
    E --> Ranking
```

### System boundary

| 포함 | 설명 |
|---|---|
| 회사명 기반 공식자료 수집 | 공식 URL, OpenDART 기반 회사 자료 수집 |
| 내부 문서 ingestion | `.txt`, `.md`, `.pdf`, `.docx` 저장 및 RAG 색인 |
| Supervisor-Agent workflow | 상위 Agent가 하위 Agent에게 명령을 할당하고 handoff |
| Agent LLM command/reflection | 각 Agent의 prompt가 실제 LLM으로 들어가 실행 명령과 handoff 판단을 생성 |
| RAG evidence | 업무 후보별 근거 검색, citation, evidence coverage |
| Governance screening | 민감정보, 고영향, 금지 가능 후보 분류 |
| Human Review | approve/edit/reject 기록 및 보고서 반영 |
| DOCX 보고서 | 과제 제출용 보고서 초안 생성 |

| 제외 또는 제한 | 설명 |
|---|---|
| 법률 자문 | Regulatory mapping은 운영 전 법무 검토가 필요함 |
| 완성형 운영 UI | 현재 CLI/API 중심 MVP |
| LLM 단독 의사결정 | 최종 추천 상태는 tool permission, score, RAG evidence, evaluator, human review로 통제 |

---

## 7. 실행 방법

### 7.1 Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 7.2 Configure `.env`

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
AGENT_SUPERVISOR_MAX_TOOL_LOOPS=2
AGENT_SUPERVISOR_EXTRA_LOOP_ENABLED=false
```

### 7.3 Initialize DB

```bash
python -m app.db.init_pgvector
python -m app.db.create_tables
python -m app.db.migrate_discovery_metadata
python -m app.db.migrate_operational_hardening
```

### 7.4 Bootstrap company

```bash
python -m app.company_bootstrap.bootstrap \
  --company-name "삼성전자" \
  --stock-code "005930" \
  --official-url "https://www.samsung.com/sec/about-us/company-info/" \
  --official-url "https://www.samsung.com/sec/about-us/business-area/" \
  --official-url "https://www.samsung.com/sec/sustainability/overview/"
```

### 7.5 Add internal documents

```bash
python -m app.ingestion.ingest \
  --company-id <company_id> \
  --file ./data/private/sop.docx \
  --title "생산 운영 SOP" \
  --department "생산팀" \
  --security-level internal
```

### 7.6 Run analysis and report generation

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --verbose
```

workflow state 저장 위치:

```text
outputs/workflow_state_real.json
```

DOCX 보고서 생성 위치:

```text
outputs/AX_Delivery_Planner_Report_<project_id>.docx
```

추가 Agent loop를 명시적으로 허용하려면 다음 옵션을 사용한다.

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --allow-agent-extra-loop \
  --verbose
```

---

## 8. 산출물

과제 최종 제출물과 프로젝트 산출물의 대응은 다음과 같다.

| 과제 제출물 | 프로젝트 산출물 |
|---|---|
| 최종 보고서 A4 15쪽 내외 | `outputs/AX_Delivery_Planner_Report_<project_id>.docx` |
| 발표자료 10~15장 | README/보고서 내용을 기반으로 별도 PPT 작성 가능 |
| AI Agent 설계도 | README 및 `docs/AGENT_SUPERVISOR_LOOP.md`의 Mermaid diagram |
| 프로토타입 또는 데모 시나리오 | CLI/API 실행, workflow state, generated DOCX |
| 참고문헌 및 출처 목록 | `used_sources`, `report_data.references` |

보고서에 반드시 포함되어야 하는 항목도 다음과 같이 대응된다.

| 보고서 필수 항목 | 시스템 대응 |
|---|---|
| 주제 선정 배경 | README 1~2장, report introduction |
| 산업 및 업무 특성 분석 | `process_analysis`, `company_profile` |
| 현재 AI 도입 현황 | report section, references |
| 향후 AI Agent 도입 후보 10개 | `business_processes`, `priority_ranking.items` |
| MVP Agent 선정 이유 | `priority_ranking.summary`, `poc_plan.mvp_agent` |
| Agent 사용자 시나리오 | `poc_plan`, `report_data.sections` |
| 필요한 데이터와 도구 | `data_readiness`, `agent_tool_calls`, `context_evidence_package` |
| 기술 아키텍처 | README Mermaid diagram |
| Human-in-the-loop 설계 | `human_review`, `review_node` |
| 위험 요소 및 통제 방안 | `risk_governance`, `compliance_assessment` |
| 평가 지표 | `agent_evaluation`, `poc_plan.kpis` |
| 기대 효과와 한계 | `roi_cost`, `report_data.sections` |

---

## 9. 평가 기준 대응

| 평가 항목 | 배점 | 프로젝트 대응 |
|---|---:|---|
| 도메인 이해도 | 20 | 제조기업 공식자료, 업무 프로세스, 이해관계자, 규제·보안 구조 분석 |
| 현재 AI 도입 현황 분석 | 15 | 공식자료·문서 기반 사례 정리, AI 기술·사용자·한계 분석 |
| Agent 기회 발굴 | 15 | 업무 후보 10개 이상 도출, 점수화, 우선순위 산정 |
| MVP Agent 설계 | 25 | 대상 사용자, 시나리오, 데이터, tool, RAG, Human Review, 아키텍처 설계 |
| 리스크 및 평가 설계 | 10 | 환각, 개인정보, 보안, 책임, human approval, confidence/evidence 평가 |
| 프로토타입 또는 데모 | 15 | 실행 가능한 CLI/API, Agent LLM trace, workflow state, DOCX 보고서 생성 |

---

## 10. Repository structure

```text
app/
  agents/
    registry.py              # Expert Agent 계약, 역할, tool_specs
    agent_llm.py             # Agent command/reflection prompt 실행
    expert_executor.py       # Agent별 assigned tool loop 실행
    handoff.py               # Agent package와 Agent-to-Agent handoff 규칙
    tool_runtime.py          # tool permission check, audit log
  graph/
    workflow.py              # LLM-command-driven Agent-stage LangGraph workflow
    nodes.py                 # 분석 internal node 구현
    replan_node.py           # evidence gap 재수집 route
    review_node.py           # Human Review interrupt
    poc_node.py              # PoC delivery plan
  company_bootstrap/         # 회사 공식자료 수집, process discovery
  ingestion/                 # 내부 문서 ingestion/indexing
  evaluation/                # Agent/LLM quality gate
  tools/                     # report/docx/review helper

docs/
  AGENT_SUPERVISOR_LOOP.md   # Supervisor-Agent handoff 및 LLM Agent prompt 구조 설명
  EXPERT_AGENT_RUNTIME.md    # Expert Agent runtime 구조 설명

outputs/
  workflow_state_real.json
  AX_Delivery_Planner_Report_<project_id>.docx
```

---

## 11. Tests

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
agent_llm_calls[*].kind = agent_command / agent_reflection
agent_llm_calls[*].llm_used = true 또는 fallback 사유 기록
agent_supervisor_steps 존재
agent_handoffs 존재
context_evidence_package / business_case_package / delivery_package 존재
각 Agent가 자신에게 할당된 tool만 실행
candidate별 recommended / human_review_required / evidence_insufficient 상태 분리
DOCX 보고서 생성
```
