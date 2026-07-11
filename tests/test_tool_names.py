"""Agent tool 이름 정규화 기준을 검증한다."""

from app.agents.registry import get_tool_spec
from app.agents.tool_guard import assert_tools_allowed
from app.agents.tool_names import normalize_tool_name


def test_normalize_tool_name_unifies_common_llm_spellings() -> None:
    """공백/언더스코어/하이픈 차이를 같은 tool 이름으로 비교한다."""

    assert normalize_tool_name(" LLM__critic ") == "llm critic"
    assert normalize_tool_name("llm-critic") == "llm critic"
    assert normalize_tool_name("LLM   critic") == "llm critic"


def test_registry_and_guard_share_tool_name_normalization() -> None:
    """registry lookup과 permission guard가 같은 정규화 기준을 사용한다."""

    assert_tools_allowed(
        "evaluation_critic_agent",
        ["LLM   critic", "quality-gate", "critic replan decider"],
    )
    assert get_tool_spec("evaluation_critic_agent", "LLM   critic")["name"] == "llm_critic"
