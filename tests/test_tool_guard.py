"""Agent별 허용 tool 검사와 permission error를 검증한다.
"""

import pytest

from app.agents.tool_guard import AgentToolPermissionError, assert_agent_scopes_allowed, assert_tools_allowed
from app.agents.tool_runtime import call_agent_tool


def test_tool_guard_allows_declared_tool():
    assert_tools_allowed("company_onboarding_agent", ["OpenDART client"])


def test_tool_guard_rejects_forbidden_tool():
    with pytest.raises(AgentToolPermissionError):
        assert_tools_allowed("business_case_agent", ["official URL loader"])


def test_scope_guard_rejects_cross_agent_mutation():
    with pytest.raises(AgentToolPermissionError):
        assert_agent_scopes_allowed("business_case_agent", ["compliance_assessment"])


def test_scope_guard_allows_declared_mutation():
    assert_agent_scopes_allowed("business_case_agent", ["priority_ranking"])


def test_runtime_enforces_explicit_write_scopes():
    result = call_agent_tool(
        agent_id="mcp_gateway_agent",
        tool_name="mcp_apply_human_review",
        payload={"value": 1},
        runner=lambda _: {"status": "ok"},
        write_scopes=["mcp.audit"],
    )
    assert result.result["status"] == "ok"

    with pytest.raises(AgentToolPermissionError):
        call_agent_tool(
            agent_id="mcp_gateway_agent",
            tool_name="mcp_apply_human_review",
            payload={"value": 1},
            runner=lambda _: {"status": "ok"},
            write_scopes=["priority_ranking"],
        )
