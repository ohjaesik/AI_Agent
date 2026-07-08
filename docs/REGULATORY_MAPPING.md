# Regulatory Mapping

본 문서는 AX Delivery Planner의 기술 통제를 AI 규제·표준 요구사항과 연결하기 위한 실무용 mapping이다. 법률 자문이 아니며, 운영 전 법무·보안 담당자의 검토가 필요하다.

## 1. Reference Sources

| 기준 | 주요 참고 내용 | URL |
|---|---|---|
| EU AI Act | risk-based approach, prohibited practices, high-risk obligations, transparency, human oversight, logging, robustness, cybersecurity | https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai |
| NIST AI RMF | voluntary AI risk management, trustworthiness considerations across design, development, use, evaluation | https://www.nist.gov/itl/ai-risk-management-framework |
| ISO/IEC 42001:2023 | AI management system, responsible development/use, risk and opportunity management, traceability, transparency, reliability | https://www.iso.org/standard/81230.html |
| Korea AI Basic Act | high-impact AI, human oversight, AI-generated content notification/labeling, explainability, safety/reliability, business responsibility. 공식 조문·시행령·고시 확정본은 운영 전 재확인 필요 | https://www.reuters.com/world/asia-pacific/south-korea-launches-landmark-laws-regulate-ai-startups-warn-compliance-burdens-2026-01-22/ |

## 2. Control Mapping

| Control ID | 시스템 구현 | EU AI Act 대응 | NIST AI RMF 대응 | ISO/IEC 42001 대응 | 한국 AI 기본법 대응 |
|---|---|---|---|---|---|
| prohibited_use_screening | `app/compliance/assessment.py` 금지 키워드 탐지 | unacceptable risk practices 차단 | MAP/MANAGE 단계에서 misuse risk 식별 | AI use risk treatment | 부적절·금지 가능 AI 활용 사전 차단 |
| high_impact_screening | healthcare, finance, employment, critical infrastructure 등 분류 | high-risk AI use case 식별 | MAP 단계의 context/risk categorization | AI risk assessment | 고영향 AI 가능 영역 사전 식별 |
| human_oversight | `human_review` interrupt, approve/edit/reject | high-risk AI human oversight | GOVERN/MANAGE accountability | responsibility/operation control | 사람 감독 및 최종 승인 기록 |
| transparency_disclosure | 보고서 status, generation mode, citation validation | transparency obligations | trustworthiness documentation | transparency/reliability | AI 생성/보조 산출물 고지 |
| explainability_notice | score_rationale, evidence label, confidence, review 기록 | explanation and transparency support | MEASURE/MANAGE explainability | documented information | 추천 근거·한계·검토 상태 표시 |
| traceability_logging | audit_logs, analysis_results, evidence_items | logging and technical documentation | MEASURE/MANAGE evidence | documented information | 신뢰성·책임 추적을 위한 기록 관리 |
| data_quality_governance | data_readiness, source metadata, RAG evidence count | data governance, dataset quality | MEASURE data quality | data lifecycle control | 데이터 품질·출처·접근권한 관리 |
| security_privacy_controls | security_level, allowed_roles, sensitive flags | cybersecurity, privacy-related safeguards | security/resilience | risk treatment/security linkage | 개인정보·기밀정보 보호 및 강화 검토 |
| safety_reliability_management | Agent Evaluator, LLM Critic, Replan, quality gate | robustness and accuracy management | MEASURE/MANAGE reliability | AI performance monitoring | 안전성·신뢰성 확보 및 낮은 confidence 추천 차단 |
| assistive_use_boundary | 자동 실행 금지, PoC 추천·보고서 생성으로 제한 | risk minimization | scope/context control | intended use boundary | 판단 보조·사람 승인 구조 |

## 3. Code-level Regulatory Mapping Rules

`app/compliance/regulatory_mapping.py`는 compliance level을 다음 규제 mapping으로 변환한다.

| Rule ID | Framework | Risk category | Level | Trigger |
|---|---|---|---|---|
| `eu_ai_act_prohibited_use` | EU AI Act | unacceptable_risk_prohibited_practice | blocked | social scoring, prohibited biometric use, emotion recognition, manipulation, predictive policing |
| `eu_ai_act_high_risk` | EU AI Act | high_risk_ai_system | enhanced_review | employment, finance, healthcare, education, critical infrastructure, law/public service |
| `korea_ai_basic_act_high_impact` | Korea AI Basic Act | high_impact_ai_operational_proxy | enhanced_review | user-impacting high-impact AI 가능 영역 |
| `privacy_confidential_data` | Privacy/Security Governance | personal_or_confidential_data_processing | sensitive_review | 개인정보, 고객정보, 계좌, 기밀, 영업비밀, restricted access |
| `standard_assistive_ai` | Korea AI Basic Act / NIST AI RMF / ISO 42001 | standard_assistive_ai | standard | 일반 문서 검색·요약·보고서 작성 보조 |

각 process item에는 다음 필드가 추가된다.

- `regulatory_mappings`
- `regulatory_summary.frameworks`
- `regulatory_summary.risk_categories`
- `regulatory_summary.required_controls`
- `regulatory_summary.obligations`

전체 assessment summary에는 다음 집계가 추가된다.

- `framework_counts`
- `risk_category_counts`

## 4. Korea AI Basic Act Operational Mapping

아래 mapping은 AX Planner 내부 통제 기준이다. 조항 번호 확정 mapping이 아니라, 공식 조문·시행령·고시 확인 전 단계의 운영형 control mapping이다.

| 운영 요구 | AX Planner 적용 방식 | 산출 증빙 |
|---|---|---|
| 고영향 AI 가능성 식별 | 업무명·문제·대상 사용자·보안등급에서 채용, 금융, 의료, 교육, 공공서비스, 핵심 인프라, 안전 관련 키워드 탐지 | `compliance_assessment.items[].high_impact_categories` |
| 사람 감독 | `human_review` node에서 approve/edit/reject와 reviewer/comment 기록 | `human_review`, `audit_logs` |
| AI 생성/보조 산출물 고지 | report status, generation mode, citation validation, AI 보조 산출물 문구 삽입 | `report_data.generation`, `citation_validation` |
| 설명가능성 | 후보별 score_rationale, evidence label, confidence, critic verdict 제공 | `priority_ranking.items[].score_rationale`, `agent_evaluation` |
| 안전성·신뢰성 | Agent Evaluator와 LLM Critic으로 confidence/evidence 부족 후보 차단 | `agent_evaluation.summary`, `llm_critic`, `quality_gate` |
| 데이터 거버넌스 | 공식 URL/문서 source, chunk metadata, security_level, allowed_roles 관리 | `used_sources`, `documents`, `document_chunks` |
| 개인정보·기밀 보호 | 민감 키워드와 보안등급 기반 sensitive_review 전환 | `risk_governance`, `security_privacy_controls` |
| 책임 추적 | node별 analysis_result, audit_log, used_sources 저장 | `analysis_results`, `audit_logs` |
| 자동 실행 제한 | PoC 후보 추천·보고서 생성으로 제한하고 업무 시스템 자동 실행 tool 미제공 | `mvp_agent.type=assistive_ai_agent` |

## 5. Compliance Levels

| Level | 의미 | 한국 AI 기본법 운영 대응 | 시스템 처리 |
|---|---|---|---|
| standard | 일반 AX 후보 | AI 보조 산출물 고지, 근거 기록, 사람 승인 전 최종 의사결정 사용 금지 | recommended 가능 |
| sensitive_review | 개인정보·기밀·지식재산 등 민감 신호 | 민감정보·기밀정보 포함 가능성 검토, 접근권한·데이터 최소화 확인 | Human Review 필요 |
| enhanced_review | 고영향 AI 가능성 | 고영향 AI 가능성 검토, 설명가능성·기록관리·데이터 품질 증빙, 법무·보안 승인 | Human Review 및 강화 통제 필요 |
| blocked | 부적절·금지 가능 사용 | 법무 검토 전 추천·PoC 진행 금지 | MVP 후보 제외 |

## 6. Current System Classification

AX Delivery Planner는 현재 다음 범위로 제한한다.

- 업무 실행 자동화 시스템이 아니라 AX 후보 추천·PoC 기획 보조 시스템
- 채용/금융/의료/안전 인프라 직접 의사결정 시스템이 아님
- 보고서와 추천 결과는 Human Review 이전에는 최종 의사결정으로 사용하지 않음
- `blocked` 후보는 MVP 후보에서 제외
- `sensitive_review`, `enhanced_review` 후보는 Human Review 필요

## 7. Test command

```bash
pytest tests/test_regulatory_mapping.py
```

## 8. Remaining Legal Work

- 국가법령정보센터 원문 기준 조항 번호 확정
- 시행령·고시·가이드라인 확정본 반영
- 개인정보보호법/영업비밀보호법/산업기술보호법과의 교차 검토
- 고객사 산업별 sector regulation mapping
- 외부 배포 시 이용자 고지문 및 책임 범위 문구 검토
