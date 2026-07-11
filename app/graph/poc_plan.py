"""PoC delivery plan의 milestone/KPI builder.

`poc_delivery_planner_node`는 DB 저장과 state 반환을 담당하고, 이 모듈은 후보 업무를
6주 PoC 실행 계획으로 바꾸는 순수 생성 로직만 담당한다. 순수 함수로 분리해두면
Human Review 정책이나 node 저장 방식이 바뀌어도 PoC 산출물 테스트를 작게 유지할 수 있다.
"""

from __future__ import annotations

from typing import Any


def build_poc_milestones(candidate: dict[str, Any] | None) -> list[dict[str, Any]]:
    """선정 후보의 업무/Agent 이름과 리스크를 반영해 6주 PoC milestone을 만든다."""

    agent_name = (candidate or {}).get("candidate_agent_name") or "선정 Agent"
    process_name = (candidate or {}).get("process_name") or "선정 업무"
    risk_flags = (candidate or {}).get("risk_flags") or []
    needs_security_review = any(flag != "standard_review" for flag in risk_flags)

    milestones = [
        {
            "phase": "1. Scope Freeze",
            "period": "Week 1",
            "owner": "IT기획 + 현업 부서",
            "tasks": [
                f"{process_name}의 대상 사용자, 입력 문서, 기대 산출물 확정",
                "PoC 성공 기준과 제외 범위 확정",
                "RAG에 사용할 공식/내부 문서 목록 확정",
            ],
            "deliverable": "PoC 범위 정의서 및 데이터 접근 체크리스트",
        },
        {
            "phase": "2. Data & RAG Readiness",
            "period": "Week 2",
            "owner": "IT/데이터 담당자",
            "tasks": [
                "문서 수집·정제·chunking·embedding 재색인",
                "근거 label과 reference mapping 검증",
                "민감정보 포함 여부와 접근권한 점검",
            ],
            "deliverable": "RAG 인덱스 검증표 및 근거 품질 리포트",
        },
        {
            "phase": "3. Agent Prototype",
            "period": "Week 3-4",
            "owner": "AI/AX 개발 담당자",
            "tasks": [
                f"{agent_name} 질의응답/추천 흐름 구현",
                "Top candidate 업무 시나리오 5~10개 테스트",
                "근거 없는 답변 차단 및 citation validation 적용",
            ],
            "deliverable": "Agent prototype, 테스트 로그, 실패 케이스 목록",
        },
        {
            "phase": "4. User Review & Governance",
            "period": "Week 5",
            "owner": "현업 부서장 + 보안/거버넌스",
            "tasks": [
                "현업 사용자 리뷰와 Human Review 기록 수집",
                "오답·누락·권한 이슈 분류",
                "운영 전 통제 조건과 승인 절차 확정",
            ],
            "deliverable": "Human Review 결과표 및 Governance 체크리스트",
        },
        {
            "phase": "5. Go/No-Go Decision",
            "period": "Week 6",
            "owner": "AX 의사결정 협의체",
            "tasks": [
                "PoC KPI 달성 여부 평가",
                "ROI 추정치와 실제 테스트 절감 효과 비교",
                "확대 적용, 보완, 중단 중 후속 의사결정",
            ],
            "deliverable": "Go/No-Go 판단 보고서 및 후속 로드맵",
        },
    ]

    if needs_security_review:
        milestones[0]["tasks"].append("민감 키워드 탐지 업무로 분류하여 보안 담당자 사전 승인 확보")
        milestones[3]["tasks"].append("개인정보·기밀정보 처리 기준과 로그 보관 정책 검토")

    return milestones


def build_poc_kpis(candidate: dict[str, Any] | None) -> list[dict[str, Any]]:
    """선정 후보의 절감률을 반영해 PoC 성공 여부를 판단할 KPI 목록을 만든다."""

    candidate = candidate or {}
    return [
        {
            "kpi": "근거 포함 응답률",
            "target": "90% 이상",
            "measurement": "Agent 응답 중 citation label을 포함한 응답 비율",
        },
        {
            "kpi": "업무 처리 시간 절감률",
            "target": f"{candidate.get('saving_rate', 50)}% 수준 검증",
            "measurement": "현행 처리 시간 대비 Agent 보조 처리 시간 비교",
        },
        {
            "kpi": "Human Review 승인율",
            "target": "80% 이상",
            "measurement": "현업/IT/보안 검토자가 승인한 응답 또는 추천 비율",
        },
        {
            "kpi": "근거 불일치율",
            "target": "5% 이하",
            "measurement": "citation과 실제 근거 내용이 불일치한 케이스 비율",
        },
        {
            "kpi": "보안 예외 발생 건수",
            "target": "0건",
            "measurement": "민감정보 노출, 권한 없는 문서 접근, 로그 누락 건수",
        },
    ]
