# AI Governance Baseline for AX Supervisor Graph

본 문서는 AX Delivery Planner를 9개 Agent 기반 Supervisor Graph로 운영하기 위한 AI Governance 기준을 정리한다. 법률 자문 문서가 아니라, 개발·시연·PoC 단계에서 적용할 기술적 통제 기준이다.

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

## 3. 9개 Agent와 통제 기준

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
| Priority & Delivery Agent | 우선순위·Human Review·PoC·보고서 | Human Review gate, transparency disclosure, citation validation |

## 4. Compliance levels

| Level | 의미 | 처리 |
|---|---|---|
| standard | 일반 AX 후보 | recommended 가능 |
| sensitive_review | 개인정보·기밀·지식재산 등 민감 신호 | Human Review 필요 |
| enhanced_review | 채용·금융·의료·안전 등 고영향 가능성 | Human Review 및 강화 통제 필요 |
| blocked | 금지 또는 부적절 사용 가능성 | MVP 후보 제외 |

## 5. 필수 통제

### 5.1 Prohibited-use screening

다음 유형의 후보는 PoC 후보에서 제외하거나 별도 법무 검토 없이는 진행하지 않는다.

- 사회적 점수화
- 무차별 얼굴 인식 DB 구축
- 취약성 악용
- 감정 인식 기반 근로자/학생 평가
- 범죄 예측 또는 개인 위험도 평가
- 사용자 기만 또는 조작 목적의 AI

### 5.2 High-impact screening

다음 영역은 기본적으로 `enhanced_review`로 분류한다.

- 채용·인사·근로자 관리
- 금융·신용·대출·보험
- 의료·진단·환자 관리
- 교통·전력·수도·원전 등 핵심 인프라
- 교육 평가·입학·성적
- 법률·사법·공공서비스 접근

### 5.3 Human oversight

모든 PoC 착수는 Human Review 이후 결정한다.

- reviewer_name
- decision: approve/edit/reject
- comment
- edited_payload
- review_channel

### 5.4 Transparency

보고서에는 다음을 표시한다.

- AI 보조 산출물 상태: draft/reviewed/final
- 사용한 근거 source와 citation label
- report_writer mode
- citation validation 결과
- Human Review 기록

### 5.5 Traceability

다음 데이터는 저장되어야 한다.

- analysis_results
- audit_logs
- used_sources
- evidence_items
- discovery_metadata
- compliance_assessment

## 6. 구현 상태

현재 구현된 항목:

- `app/agents/registry.py`: 9개 Agent registry
- `app/compliance/regulatory_policy.py`: regulatory control mapping
- `app/compliance/assessment.py`: prohibited/high-impact/sensitive screening
- `app/graph/compliance_node.py`: LangGraph compliance assessment node
- `app/graph/workflow.py`: risk_governance 이후 compliance_assessment 실행
- `app/tools/score_calculator.py`: compliance 결과를 ranking status/reason에 반영

다음 구현 대상:

- 병렬 graph 전환을 위한 state reducer 적용
- compliance assessment 보고서 섹션 추가
- API/UI에서 compliance 결과 표시
- 고위험 카테고리별 추가 질문지 및 checklist
- 문서별 접근권한/삭제/재처리 workflow
