# app/agents/tool_guard.py

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from app.agents.registry import get_agent_spec

F = TypeVar("F", bound=Callable[..., Any])


class AgentToolPermissionError(PermissionError):
    pass


def normalize_tool_name(tool: str) -> str:
    return " ".join(str(tool or "").lower().replace("_", " ").replace("-", " ").split())


def get_allowed_tools(agent_id: str) -> set[str]:
    spec = get_agent_spec(agent_id)
    if not spec:
        raise AgentToolPermissionError(f"Unknown agent_id: {agent_id}")
    return {normalize_tool_name(tool) for tool in spec.get("tools", [])}


def assert_tools_allowed(agent_id: str, requested_tools: list[str]) -> None:
    allowed = get_allowed_tools(agent_id)
    requested = {normalize_tool_name(tool) for tool in requested_tools}
    denied = sorted(tool for tool in requested if tool not in allowed)
    if denied:
        raise AgentToolPermissionError(
            f"Agent '{agent_id}' requested forbidden tools: {denied}. "
            f"Allowed tools: {sorted(allowed)}"
        )


def enforce_agent_tools(agent_id: str, requested_tools: list[str]) -> Callable[[F], F]:
    """Decorator for runtime tool permission checks.

    This is not a sandbox. It is a runtime contract gate that ensures every graph
    node declares tools that are present in Agent Registry before it runs.
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

    return [
        {
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name"),
            "allowed_tools": agent.get("tools", []),
            "controls": agent.get("controls", []),
        }
        for agent in get_agent_registry()
    ]
