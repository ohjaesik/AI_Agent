"""업무 분석/스코어링 graph node의 기본 산출물을 검증한다."""

from app.graph import analysis_nodes
from app.graph.node_worker import NODE_TARGETS, import_node


class FakeSession:
    """DB 저장 호출을 막기 위한 테스트용 context manager."""

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


def patch_db_writes(monkeypatch) -> list[dict[str, object]]:
    """analysis node가 DB 저장 대신 기록 리스트에 payload를 남기게 바꾼다."""

    saved: list[dict[str, object]] = []
    monkeypatch.setattr(analysis_nodes, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        analysis_nodes,
        "save_analysis_result",
        lambda **kwargs: saved.append(kwargs),
    )
    return saved


def test_analysis_node_worker_targets_use_analysis_module() -> None:
    """worker mapping이 분리된 analysis_nodes 모듈을 직접 가리킨다."""

    assert NODE_TARGETS["process_analyzer"] == "app.graph.analysis_nodes:process_analyzer_node"
    assert import_node("process_analyzer") is analysis_nodes.process_analyzer_node


def test_process_analyzer_uses_retrieved_context_and_citation(monkeypatch) -> None:
    """process analyzer가 RAG context와 evidence citation을 분석 결과에 연결한다."""

    saved = patch_db_writes(monkeypatch)
    result = analysis_nodes.process_analyzer_node(
        {
            "project_id": 1,
            "business_processes": [
                {
                    "id": 10,
                    "name": "계약 검토",
                    "target_user": "법무팀",
                    "candidate_agent_name": "Contract Agent",
                    "problem": "수작업 검토 지연",
                    "current_workflow": "이메일 접수 후 수동 검토",
                    "repeatability": 5,
                    "document_dependency": 4,
                }
            ],
            "retrieved_contexts": {"10": [{"content": "계약 검토 근거 본문"}]},
            "evidence_items": [{"process_id": 10, "citation_label": "[RAG-1]"}],
        }
    )

    item = result["process_analysis"]["items"][0]
    assert item["evidence"] == "계약 검토 근거 본문"
    assert item["citation_label"] == "[RAG-1]"
    assert result["process_analysis"]["summary"]["high_repeatability_count"] == 1
    assert saved[0]["node_name"] == "process_analyzer"


def test_data_readiness_and_automation_feasibility_summaries(monkeypatch) -> None:
    """readiness/feasibility node가 low/high summary count를 계산한다."""

    patch_db_writes(monkeypatch)
    state = {
        "project_id": 1,
        "business_processes": [
            {
                "id": 1,
                "name": "정산",
                "data_accessibility": 2,
                "expected_effect": 5,
                "repeatability": 5,
                "tech_feasibility": 5,
                "risk_score": 1,
            }
        ],
    }

    readiness = analysis_nodes.data_readiness_node(state)
    feasibility = analysis_nodes.automation_feasibility_node(state)

    assert readiness["data_readiness"]["summary"]["low_readiness_count"] == 1
    assert feasibility["automation_feasibility"]["summary"]["high_feasibility_count"] == 1
    assert feasibility["automation_feasibility"]["items"][0]["expected_time_reduction_rate"] == 0.7
