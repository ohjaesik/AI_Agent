# Korea AI Basic Act Operational Mapping

본 문서는 AX Delivery Planner의 내부 운영 통제 mapping이다. 법률 자문이 아니며, 운영 전 국가법령정보센터 원문, 시행령, 고시, 주무부처 가이드라인을 기준으로 재검토해야 한다.

## 적용 관점

AX Delivery Planner는 업무 실행 자동화 시스템이 아니라 AX 후보 추천·PoC 기획 보조 시스템이다. 따라서 기본 통제 방향은 다음과 같다.

- AI 산출물 고지
- 고영향 AI 가능성 사전 식별
- 사람 감독 및 최종 승인
- 설명가능성 확보
- 데이터 품질·출처·권한 관리
- 민감정보·기밀정보 보호
- 낮은 confidence 후보의 자동 추천 차단

## Compliance Level Mapping

| Level | 의미 | 처리 |
|---|---|---|
| standard | 일반 AX 후보 | AI 보조 산출물 고지, 근거 기록, 사람 승인 전 최종 의사결정 사용 금지 |
| sensitive_review | 개인정보·기밀·지식재산 등 민감 신호 | Human Review, 접근권한·데이터 최소화 확인 |
| enhanced_review | 고영향 AI 가능성 | Human Review, 법무·보안 owner 승인, 설명가능성·데이터 품질 증빙 |
| blocked | 부적절·금지 가능 사용 | MVP 후보 제외, 법무 검토 전 PoC 진행 금지 |

## System Evidence

| 운영 요구 | 코드/산출물 |
|---|---|
| 고영향 가능성 식별 | `app/compliance/assessment.py`, `high_impact_categories` |
| 사람 감독 | `human_review`, reviewer, decision, comment |
| AI 보조 산출물 고지 | report status, generation mode, citation validation |
| 설명가능성 | score_rationale, evidence_labels, confidence_score, critic verdict |
| 안전성·신뢰성 | Agent Evaluator, LLM Critic, Replan Loop, quality gate |
| 데이터 거버넌스 | used_sources, document_chunks, security_level, allowed_roles |
| 민감정보 보호 | sensitive_review, security_privacy_controls |
| 책임 추적 | analysis_results, audit_logs |
| 자동 실행 제한 | `mvp_agent.type=assistive_ai_agent` |

## 구현 파일

- `app/compliance/regulatory_policy.py`
- `app/compliance/assessment.py`
- `docs/REGULATORY_MAPPING.md`
- `tests/test_korea_ai_basic_act_mapping.py`

## 남은 법무 검토

- 공식 조문 번호 확정
- 시행령·고시·가이드라인 반영
- 개인정보보호법, 영업비밀보호법, 산업기술보호법 교차 검토
- 고객사 산업별 sector regulation mapping
