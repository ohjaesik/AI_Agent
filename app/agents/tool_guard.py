# app/agents/tool_guard.py

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from app.agents.registry import get_agent_registry, get_agent_spec, get_tool_spec
from app.agents.sandbox import SandboxResult, run_sandboxed_command

F = TypeVar("F", bound=Callable[..., Any])


class AgentToolPermissionError(PermissionError):
    pass


def normalize_tool_name(tool: str) -> str:
    return " ".join(str(tool or "").lower().replace("_", " ").replace("-", " ").split())


def get_allowed_tools(agent_id: str) -> set[str]:
    spec = get_agent_spec(agent_id)
    if not spec:
        raise AgentToolPermissionError(f"Unknown agent_id: {agent_id}")

    explicit_tools = {normalize_tool_name(tool) for tool in spec.get("tools", [])}
    spec_tools = {normalize_tool_name(tool.get("name")) for tool in spec.get("tool_specs", []) or [] if tool.get("name")}
    return explicit_tools | spec_tools


def assert_tools_allowed(agent_id: str, requested_tools: list[str]) -> None:
    allowed = get_allowed_tools(agent_id)
    requested = {normalize_tool_name(tool) for tool in requested_tools}
    denied = sorted(tool for tool in requested if tool not in allowed)
    if denied:
        raise AgentToolPermissionError(
            f"Agent '{agent_id}' requested forbidden tools: {denied}. "
            f"Allowed tools: {sorted(allowed)}"
        )


def assert_tool_spec_allowed(agent_id: str, tool_name: str) -> dict[str, Any]:
    assert_tools_allowed(agent_id=agent_id, requested_tools=[tool_name])
    spec = get_tool_spec(agent_id, tool_name)
    if not spec:
        raise AgentToolPermissionError(
            f"Agent '{agent_id}' is allowed to reference '{tool_name}', but no tool_specs contract was found."
        )
    return spec


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
    return [
        {
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name"),
            "allowed_tools": sorted(get_allowed_tools(str(agent.get("id")))),
            "tool_specs": agent.get("tool_specs", []),
            "controls": [*agent.get("controls", []), "runtime_tool_permission_check"],
        }
        for agent in get_agent_registry()
    ]
