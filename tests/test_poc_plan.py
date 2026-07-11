"""PoC plan builder의 milestone/KPI 생성을 검증한다."""

from app.graph.poc_plan import build_poc_kpis, build_poc_milestones


def test_build_poc_milestones_reflects_process_agent_and_security_review() -> None:
    """선정 후보의 업무명/Agent명/보안 리스크가 milestone task에 반영된다."""

    milestones = build_poc_milestones(
        {
            "process_name": "계약 검토",
            "candidate_agent_name": "Contract Review Agent",
            "risk_flags": ["sensitive_review"],
        }
    )

    flattened_tasks = " ".join(task for milestone in milestones for task in milestone["tasks"])

    assert len(milestones) == 5
    assert "계약 검토" in flattened_tasks
    assert "Contract Review Agent" in flattened_tasks
    assert "보안 담당자 사전 승인" in flattened_tasks


def test_build_poc_kpis_uses_candidate_saving_rate_or_default() -> None:
    """후보에 saving_rate가 있으면 KPI target에 반영하고 없으면 기본 50%를 쓴다."""

    assert build_poc_kpis({"saving_rate": 35})[1]["target"] == "35% 수준 검증"
    assert build_poc_kpis(None)[1]["target"] == "50% 수준 검증"
