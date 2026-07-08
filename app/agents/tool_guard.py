# app/agents/tool_guard.py

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from app.agents.registry import get_agent_spec
from app.agents.sandbox import SandboxResult, run_sandboxed_command

F = TypeVar("F", bound=Callable[..., Any])

FALLBACK_AGENT_TOOLS = {
    "agent_evaluator_agent": [
        "agent evaluator",
        "LLM critic",
        "evidence coverage scorer",
        "tool permission checker",
        "analysis result writer",
    ],
}


class AgentToolPermissionError(PermissionError):
    pass


def normalize_tool_name(tool: str) -> str:
    return " ".join(str(tool or "").lower().replace("_", " ").replace("-", " ").split())


def get_allowed_tools(agent_id: str) -> set[str]:
    spec = get_agent_spec(agent_id)
    if spec:
        return {normalize_tool_name(tool) for tool in spec.get("tools", [])}
    if agent_id in FALLBACK_AGENT_TOOLS:
        return {normalize_tool_name(tool) for tool in FALLBACK_AGENT_TOOLS[agent_id]}
    raise AgentToolPermissionError(f"Unknown agent_id: {agent_id}")


def assert_tools_allowed(agent_id: str, requested_tools: list[str]) -> None:
    allowed = get_allowed_tools(agent_id)
    requested = {normalize_tool_name(tool) for tool in requested_tools}
    denied = sorted(tool for tool in requested if tool not in allowed)
    if denied:
        raise AgentToolPermissionError(
            f"Agent '{agent_id}' requested forbidden tools: {denied}. "
            f"Allowed tools: {sorted(allowed)}"
        )


def run_allowed_command_tool(agent_id: str, tool_name: str, command: list[str], timeout_seconds: int | None = None) -> SandboxResult:
    """Run a command tool only after permission check, optionally inside Docker sandbox.

    Use this for command-style tools. Normal Python function tools should still be
    called directly but must use assert_tools_allowed or enforce_agent_tools.
    """
    assert_tools_allowed(agent_id=agent_id, requested_tools=[tool_name])
    return run_sandboxed_command(command=command, timeout_seconds=timeout_seconds)


def enforce_agent_tools(agent_id: str, requested_tools: list[str]) -> Callable[[F], F]:
    """Decorator for runtime tool permission checks.

    This is not a full Python object sandbox. It is a runtime contract gate.
    Command-style tools can use run_allowed_command_tool for Docker isolation.
    """
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            assert_tools_allowed(agent_id=agent_id, requested_tools=requested_tools)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def build_tool_permission_report() -> list[dict[str, Any]]:
    from app.agents.registry import get_agent_registry

    rows = [
        {
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name"),
            "allowed_tools": agent.get("tools", []),
            "controls": [*agent.get("controls", []), "runtime_tool_permission_check"],
        }
        for agent in get_agent_registry()
    ]
    rows.extend(
        {
            "agent_id": agent_id,
            "agent_name": agent_id,
            "allowed_tools": tools,
            "controls": ["runtime_tool_permission_check", "optional_docker_command_sandbox"],
        }
        for agent_id, tools in FALLBACK_AGENT_TOOLS.items()
    )
    return rows
