# app/agents/registry.py

from __future__ import annotations

from typing import Any

from app.agents.expert_registry import (
    EXPERT_AGENT_REGISTRY,
    ExpertAgentSpec,
    get_capability_for_node,
    get_expert_agent_registry,
    get_expert_agent_spec,
)

# Backward-compatible names. The runtime now treats the registry as an expert-agent
# execution contract registry rather than a tool/node-level catalog.
AgentSpec = ExpertAgentSpec
AGENT_REGISTRY = EXPERT_AGENT_REGISTRY


def get_agent_registry() -> list[dict[str, Any]]:
    """Return the expert-level Agent Registry used by graph runtime.

    Kept for compatibility with older imports. The returned records are the
    7 expert Agent contracts, each with managed_nodes and capabilities.
    """
    return get_expert_agent_registry()


def get_agent_spec(agent_id: str) -> dict[str, Any] | None:
    """Return an expert AgentSpec by id.

    Kept for compatibility with older imports that expected get_agent_spec().
    """
    return get_expert_agent_spec(agent_id)


__all__ = [
    "AgentSpec",
    "AGENT_REGISTRY",
    "get_agent_registry",
    "get_agent_spec",
    "get_capability_for_node",
]
