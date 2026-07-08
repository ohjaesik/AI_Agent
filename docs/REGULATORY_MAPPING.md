# Regulatory Mapping

본 문서는 AX Delivery Planner의 기술 통제를 AI 규제·표준 요구사항과 연결하기 위한 실무용 mapping이다. 법률 자문이 아니며, 운영 전 법무·보안 담당자의 검토가 필요하다.

## 1. Reference Sources

| 기준 | 주요 참고 내용 | URL |
|---|---|---|
| EU AI Act | risk-based approach, prohibited practices, high-risk obligations, transparency, human oversight, logging, robustness, cybersecurity | https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai |
| NIST AI RMF | voluntary AI risk management, trustworthiness considerations across design, development, use, evaluation | https://www.nist.gov/itl/ai-risk-management-framework |
| ISO/IEC 42001:2023 | AI management system, responsible development/use, risk and opportunity management, traceability, transparency, reliability | https://www.iso.org/standard/81230.html |
| Korea AI Basic Act | high-impact AI, human oversight, AI-generated content notification/labeling 등은 보도 기준으로 반영. 조항별 원문 검토 필요 | https://www.reuters.com/world/asia-pacific/south-korea-launches-landmark-laws-regulate-ai-startups-warn-compliance-burdens-2026-01-22/ |

## 2. Control Mapping

| Control ID | 시스템 구현 | EU AI Act 대응 | NIST AI RMF 대응 | ISO/IEC 42001 대응 | 한국 AI 기본법 대응 |
|---|---|---|---|---|---|
| prohibited_use_screening | `app/compliance/assessment.py` 금지 키워드 탐지 | unacceptable risk practices 차단 | MAP/MANAGE 단계에서 misuse risk 식별 | AI use risk treatment | 금지·부적절 활용 방지 목적 |
| high_impact_screening | healthcare, finance, employment, critical infrastructure 등 분류 | high-risk AI use case 식별 | MAP 단계의 context/risk categorization | AI risk assessment | 고영향 AI 사전 식별 |
| human_oversight | `human_review` interrupt, approve/edit/reject | high-risk AI human oversight | GOVERN/MANAGE accountability | responsibility/operation control | 고영향 AI 사람 감독 원칙 |
| transparency_disclosure | 보고서 status, generation mode, citation validation | transparency obligations | trustworthiness documentation | transparency/reliability | AI 생성/보조 산출물 고지 |
| traceability_logging | audit_logs, analysis_results, evidence_items | logging and technical documentation | MEASURE/MANAGE evidence | documented information | 설명가능성·책임 추적 |
| data_quality_governance | data_readiness, source metadata, RAG evidence count | data governance, dataset quality | MEASURE data quality | data lifecycle control | 신뢰성 확보 |
| security_privacy_controls | security_level, allowed_roles, sensitive flags | cybersecurity, privacy-related safeguards | security/resilience | risk treatment/security linkage | 민감정보 보호 |
| assistive_use_boundary | 자동 실행 금지, PoC 추천·보고서 생성으로 제한 | risk minimization | scope/context control | intended use boundary | 판단 보조·사람 승인 구조 |

## 3. Current System Classification

AX Delivery Planner는 현재 다음 범위로 제한한다.

- 업무 실행 자동화 시스템이 아니라 AX 후보 추천·PoC 기획 보조 시스템
- 채용/금융/의료/안전 인프라 직접 의사결정 시스템이 아님
- 보고서와 추천 결과는 Human Review 이전에는 최종 의사결정으로 사용하지 않음
- `blocked` 후보는 MVP 후보에서 제외
- `sensitive_review`, `enhanced_review` 후보는 Human Review 필요

## 4. Remaining Legal Work

- 한국 AI 기본법 조항별 원문 확인
- 개인정보보호법/영업비밀보호법/산업기술보호법과의 교차 검토
- 고객사 산업별 sector regulation mapping
- 외부 배포 시 이용자 고지문 및 책임 범위 문구 검토
