from app.agents.registry import AGENT_REGISTRY, get_agent_registry, get_agent_spec


def test_all_agent_specs_include_operational_prompt_fields():
    for agent in get_agent_registry():
        assert agent["role_prompt"]
        assert len(agent["role_prompt"]) >= 80
        assert agent["task_instructions"]
        assert agent["output_contract"]
        assert agent["quality_checks"]
        assert agent["handoff_notes"]


def test_agent_ids_are_unique():
    ids = [agent.id for agent in AGENT_REGISTRY]

    assert len(ids) == len(set(ids))


def test_agent_evaluator_prompt_enforces_conservative_review_policy():
    spec = get_agent_spec("agent_evaluator_agent")

    assert spec is not None
    assert "evidence_coverage" in " ".join(spec["task_instructions"])
    assert "compliance" in spec["role_prompt"].lower()
    assert any("Blocked compliance" in check for check in spec["quality_checks"])
    assert any("Human Review" in note for note in spec["handoff_notes"])


def test_priority_delivery_agent_uses_human_review_gate():
    spec = get_agent_spec("priority_delivery_agent")

    assert spec is not None
    assert spec["human_review_required"] is True
    assert "human_review_gate" in spec["controls"]
    assert any("Do not select excluded" in check for check in spec["quality_checks"])
