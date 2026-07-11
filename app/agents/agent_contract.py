"""Supervisor/Expert Agent LLM 출력 계약을 보정하는 공통 함수.

LLM은 prompt에서 허용된 node만 쓰라고 해도 존재하지 않는 node를 섞거나 일부 node를
빠뜨릴 수 있다. 이 모듈은 그런 응답을 runtime이 실행 가능한 계약으로 정규화한다.
"""

from __future__ import annotations

from typing import Any


def sanitize_node_order(raw_order: Any, internal_nodes: list[str]) -> list[str]:
    """LLM이 반환한 node_order를 stage에 허용된 내부 node 목록으로 제한한다.

    허용되지 않은 node는 버리고, LLM이 빠뜨린 필수 node는 뒤에 붙인다. 이렇게 하면
    Supervisor/Expert Agent가 이상한 순서를 반환해도 stage의 기본 산출물이 누락되지
    않고, runtime은 항상 배정된 내부 node만 실행한다.
    """

    if not isinstance(raw_order, list):
        return internal_nodes
    ordered = [str(item) for item in raw_order if str(item) in internal_nodes]
    ordered += [node for node in internal_nodes if node not in ordered]
    return ordered or internal_nodes
