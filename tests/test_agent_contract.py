"""Agent LLM 출력 계약 보정 로직을 검증한다."""

from app.agents.agent_contract import sanitize_node_order


def test_sanitize_node_order_removes_unknown_nodes_and_appends_missing_nodes() -> None:
    """허용되지 않은 node를 제거하고 빠진 node를 뒤에 붙여 전체 stage를 보존한다."""

    assert sanitize_node_order(
        ["unknown", "score", "load"],
        ["load", "retrieve", "score"],
    ) == ["score", "load", "retrieve"]


def test_sanitize_node_order_uses_default_order_for_invalid_payload() -> None:
    """LLM이 list가 아닌 값을 반환하면 runtime의 기본 내부 node 순서를 사용한다."""

    assert sanitize_node_order("score,load", ["load", "score"]) == ["load", "score"]
