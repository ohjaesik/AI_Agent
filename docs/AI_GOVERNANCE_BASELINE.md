<!-- 파일 역할: AX Supervisor Graph 운영 시 적용할 AI governance 기본 통제 기준을 정리한다. -->

# AI Governance Baseline for AX Supervisor Graph

본 문서는 AX Delivery Planner를 Agent 기반 Supervisor Graph로 운영하기 위한 AI Governance 기준을 정리한다. 법률 자문 문서가 아니라, 개발·시연·PoC 단계에서 적용할 기술적 통제 기준이다.

## 1. 적용 기준

본 시스템은 다음 기준을 우선 참고한다.

- Korea AI Basic Act: 고영향 AI, 투명성, Human Oversight, AI 생성물 표시, 사업자 책임
- EU AI Act: risk-based approach, prohibited use, high-risk AI obligations, transparency, logging, human oversight, robustness, cybersecurity
- NIST AI RMF: Govern, Map, Measure, Manage 기반 AI risk management
- ISO/IEC 42001: AI management system, responsibility, lifecycle control, documented information, continuous improvement

## 2. 시스템 성격

AX Delivery Planner는 기본적으로 다음 성격의 시스템이다.

- AI Agent 도입 후보를 추천하는 판단 보조 시스템
- 회사 공식자료와 업로드 문서를 RAG로 활용하는 근거 기반 분석 시스템
- 업무 자동 실행 시스템이 아님
- 채용, 금융, 의료, 법률, 안전 인프라 의사결정 시스템이 아님
- 최종 PoC 착수 여부는 Human Review를 통해 결정

따라서 기본 위험 수준은 `limited/standard`로 보되, 업무 후보에 따라 `sensitive_review`, `enhanced_review`, `blocked`로 상향한다.

## 3. Agent와 통제 기준

| Agent | 역할 | 주요 통제 |
|---|---|---|
| Company Profile Agent | 회사명·공식 URL·OpenDART 기반 회사 프로필 생성 | 공식 출처 제한, raw web text 제거, 출처 추적 |
| Source Ingestion Agent | 문서 수집·정제·RAG 색인 | 문서 보안등급, 민감정보 탐지, chunk metadata |
| Process Discovery Agent | 공식자료 기반 업무 후보 생성 | citation label 강제, JSON 검증, fallback |
| Process Analysis Agent | 업무별 문제·병목 분석 | 근거 기반 claim, audit logging |
| Data Readiness Agent | 데이터 접근성·품질 판단 | data quality, access precondition |
| Automation Feasibility Agent | 적용 가능성·시간 절감률 판단 | assistive-only, no autonomous execution |
| ROI & Cost Agent | ROI/비용 계산 | deterministic formula, no LLM financial guessing |
| Risk & Governance Agent | 위험·고영향·민감정보 평가 | prohibited-use screening, high-impact screening |
| Compliance Assessment Agent | 규제 검토 수준 산정 | blocked/sensitive/enhanced gating |
| Priority & Delivery Agent | 우선순위·Human Review·PoC·보고서 | Human Review gate, transparency disclosure, citation validation |
| Agent Evaluator / Critic | 후보별 confidence, evidence coverage, LLM second opinion 검증 | tool permission check, confidence gate, replan loop |

Agent Evaluator / Critic은 후보를 새로 생성하지 않고 기존 Agent 출력의 근거 coverage, confidence, compliance alignment를 재검증한다.

## 4. Supervisor Graph 실행 구조

### 4.1 Bootstrap Supervisor Graph

```text
START
→ company_profile_agent
→ source_ingestion_agent
→ process_discovery_agent
→ END
```

### 4.2 AX Analysis Supervisor Graph

```text
START
→ load_project_data
→ retrieve_context
  ├─ process_analyzer
  ├─ data_readiness
  ├─ automation_feasibility → roi_cost
  └─ risk_governance → compliance_assessment
→ priority_ranking
→ agent_evaluator
→ llm_critic
  ├─ agent_replan → retrieve_context  # max 1회
  └─ human_review
→ poc_delivery_planner
→ report_writer
→ docx_generator
→ END
```

병렬 branch가 동시에 `audit_logs`, `errors`를 갱신하므로 `AXPlannerState`에는 dedupe reducer를 적용한다.

## 5. Runtime Tool Permission

`app/agents/tool_guard.py`는 Agent Registry에 등록된 도구 목록과 실제 노드가 요청한 도구 목록을 비교한다.

- 등록된 도구만 실행 가능
- 등록되지 않은 도구 요청 시 `AgentToolPermissionError`
- 현재는 sandbox가 아니라 runtime contract gate
- 노드 실행 전 명시적 권한 확인을 통해 Agent별 권한 범위를 드러낸다

예시:

```text
ROI & Cost Agent는 cost calculator/ROI formula 계열만 허용한다.
ROI & Cost Agent가 official URL loader를 요청하면 차단한다.
```

## 6. Agent Evaluator 기준

| 지표 | 의미 | 활용 |
|---|---|---|
| confidence_score | 근거, 데이터, 점수 근거, compliance 정합성을 합산한 신뢰도 | 낮으면 Human Review 또는 추가 근거 수집 |
| evidence_coverage | discovery evidence label, RAG context, evidence item coverage | 낮으면 evidence_insufficient |
| data_confidence | 데이터 접근성 및 context 확보 수준 | 낮으면 데이터 준비 필요 |
| rationale_coverage | 점수 산정 근거의 완성도 | 낮으면 Human Review 필요 |
| compliance_alignment | compliance 상태와 ranking status의 정합성 | 충돌 시 Human Review 또는 excluded |
| risk_uncertainty | 위험 점수와 규제 level 기반 불확실성 | confidence 감점 |

정책은 다음과 같다.

- `confidence_score < 0.50`: `evidence_insufficient`
- `confidence_score < 0.75`: `human_review_required`
- `blocked=True`: `excluded`
- `sensitive_review` 또는 `enhanced_review`: recommended 유지 불가, Human Review 필요

## 7. LLM Critic

LLM Critic은 Agent Evaluator 이후 second-opinion 검토를 수행한다.

- 입력: candidate JSON, deterministic evaluation JSON
- 출력: `pass`, `needs_review`, `insufficient_evidence`, `reject`
- 외부 사실 추가 금지
- LLM 호출 실패, JSON 파싱 실패, vLLM 미구동 시 deterministic fallback 적용
- Critic 결과는 confidence를 제한적으로 보정하고 ranking status에 반영한다

## 8. Replan Loop

Replan Loop는 evidence coverage 또는 confidence가 부족한 후보가 있을 때 1회만 실행된다.

- `additional_evidence_required_count > 0`이면 `agent_replan`으로 이동
- `agent_replan`은 보완 필요 후보, 보완 action, requery terms를 생성
- 이후 `retrieve_context`로 돌아가 기존 RAG 문서를 1회 재검색
- 신규 공식 URL 수집이나 문서 업로드는 graph 내부 자동 실행이 아니라 Human Review/API 입력이 필요
- 1회 재검색 후에도 부족하면 Human Review로 전환

## 9. Compliance levels

| Level | 의미 | 처리 |
|---|---|---|
| standard | 일반 AX 후보 | recommended 가능 |
| sensitive_review | 개인정보·기밀·지식재산 등 민감 신호 | Human Review 필요 |
| enhanced_review | 채용·금융·의료·안전 등 고영향 가능성 | Human Review 및 강화 통제 필요 |
| blocked | 부적절 사용 가능성 | MVP 후보 제외 |

## 10. Traceability

다음 데이터는 저장되어야 한다.

- bootstrap `agent_trace`
- analysis `audit_logs`
- analysis_results
- used_sources
- evidence_items
- discovery_metadata
- compliance_assessment
- agent_evaluation
- replan_request
- llm_critic verdict

## 11. 구현 상태

현재 구현된 항목:

- `app/agents/registry.py`: Agent registry
- `app/agents/tool_guard.py`: runtime tool permission guard
- `app/agents/evaluator.py`: Agent Evaluator confidence scoring
- `app/agents/llm_critic.py`: LLM Critic + deterministic fallback
- `app/graph/agent_evaluator_node.py`: LangGraph Agent Evaluator node
- `app/graph/llm_critic_node.py`: LangGraph LLM Critic node
- `app/graph/replan_node.py`: 1회 RAG re-query 기반 Replan loop
- `app/evaluation/agent_quality_eval.py`: gold set 기반 Agent 품질 평가 runner
- `tests/data/agent_quality_gold.jsonl`: 20개 Agent 품질 평가셋
- `app/company_bootstrap/workflow.py`: Bootstrap Supervisor Graph
- `app/graph/workflow.py`: 병렬 AX Analysis Supervisor Graph, compliance fan-in, evaluator/critic/replan gate
- `app/tools/report_data_builder.py`: Agent Evaluation, LLM Critic, Replan 보고서 섹션 삽입

다음 구현 대상:

- UI를 Test UI에서 실제 wizard형 화면으로 분리
- 신규 공식 URL 자동 수집을 replan loop에 연결
- Agent 품질 평가셋 50개 이상 확대
- 법령 원문 기반 조항별 mapping 보강
