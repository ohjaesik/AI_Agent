from app.monitoring.metrics import InMemoryMetrics


def test_agent_node_metrics_render_prometheus():
    local_metrics = InMemoryMetrics()
    local_metrics.observe_agent_node("agent_evaluator", "subprocess", "success", 1.25)
    rendered = local_metrics.render_prometheus()

    assert "ax_agent_node_runs_total" in rendered
    assert 'node="agent_evaluator"' in rendered
    assert 'mode="subprocess"' in rendered
    assert 'status="success"' in rendered
    assert "ax_agent_node_latency_seconds_sum" in rendered
