"""기존 app.graph.nodes import 경로의 호환 re-export를 검증한다."""

from app.graph import analysis_nodes, nodes, poc_node, review_node


def test_nodes_reexports_split_analysis_nodes() -> None:
    """분리 전 import 경로가 새 analysis_nodes 구현을 그대로 가리킨다."""

    assert nodes.process_analyzer_node is analysis_nodes.process_analyzer_node
    assert nodes.priority_ranking_node is analysis_nodes.priority_ranking_node


def test_nodes_reexports_review_and_poc_nodes() -> None:
    """구버전 Human Review/PoC 구현 대신 최신 분리 모듈 구현을 노출한다."""

    assert nodes.human_review_node is review_node.human_review_node
    assert nodes.poc_delivery_planner_node is poc_node.poc_delivery_planner_node
