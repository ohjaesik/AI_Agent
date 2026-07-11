"""Agent별 허용 tool 검사와 permission error를 검증한다.
"""

import pytest

from app.agents.tool_guard import AgentToolPermissionError, assert_tools_allowed


def test_tool_guard_allows_declared_tool():
    assert_tools_allowed("company_onboarding_agent", ["OpenDART client"])


def test_tool_guard_rejects_forbidden_tool():
    with pytest.raises(AgentToolPermissionError):
        assert_tools_allowed("business_case_agent", ["official URL loader"])
