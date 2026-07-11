"""Agent tool 이름 비교에 쓰는 공통 정규화 함수."""

from __future__ import annotations


def normalize_tool_name(tool_name: str) -> str:
    """tool 이름 비교가 안정적으로 되도록 대소문자/구분자/공백을 정규화한다.

    LLM은 같은 tool도 `LLM critic`, `llm_critic`, `llm-critic`처럼 다르게 표현할
    수 있다. registry lookup과 permission guard가 같은 기준을 쓰도록 한곳에서
    소문자 변환, `_`/`-` 치환, 중복 공백 제거를 처리한다.
    """

    return " ".join(str(tool_name or "").lower().replace("_", " ").replace("-", " ").split())
