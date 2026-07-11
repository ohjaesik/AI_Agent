"""node worker direct/subprocess 실행 wrapper를 검증한다.
"""

import pytest

from app.graph.node_worker import NON_WORKERIZABLE_NODES, NodeWorkerError, import_node, workerized_node


def test_import_node_known_name_returns_callable():
    fn = import_node("agent_evaluator")
    assert callable(fn)


def test_import_node_rejects_unknown_name():
    with pytest.raises(NodeWorkerError):
        import_node("unknown_node")


def test_workerized_node_sets_name():
    fn = workerized_node("agent_evaluator")
    assert fn.__name__ == "workerized_agent_evaluator"


def test_human_review_is_not_workerizable():
    assert "human_review" in NON_WORKERIZABLE_NODES
