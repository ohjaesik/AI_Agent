import sys

import pytest

from app.agents.sandbox import AgentSandboxError, validate_command_safety
from app.agents.tool_guard import run_allowed_command_tool


class Settings:
    agent_tool_sandbox_mode = "direct"
    agent_tool_sandbox_image = "python:3.12-slim"
    agent_tool_sandbox_timeout_seconds = 5
    agent_tool_sandbox_network = "none"


def test_allowed_command_tool_runs_in_direct_mode(monkeypatch):
    monkeypatch.setattr("app.agents.sandbox.get_settings", lambda: Settings())
    result = run_allowed_command_tool(
        agent_id="agent_evaluator_agent",
        tool_name="agent evaluator",
        command=[sys.executable, "-c", "print('ok')"],
        timeout_seconds=5,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_sandbox_rejects_denied_executable():
    with pytest.raises(AgentSandboxError):
        validate_command_safety(["curl", "https://example.com"])


def test_sandbox_rejects_unknown_executable():
    with pytest.raises(AgentSandboxError):
        validate_command_safety(["unknown-tool", "--version"])
