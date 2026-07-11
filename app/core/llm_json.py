"""LLM prompt/response JSON 처리를 위한 공통 유틸리티.

Agent 계층에서는 Supervisor, Expert Agent, critic처럼 여러 LLM 호출부가 모두
"state 일부를 JSON 문자열로 prompt에 넣고, 모델 응답에서 JSON object를 꺼내는"
패턴을 반복한다. 이 모듈은 그 반복을 한곳으로 모아, 모델이 code fence나 앞뒤
설명을 섞어도 동일한 방식으로 복구하고 실패 시 같은 기준으로 fallback되게 한다.
"""

from __future__ import annotations

import json
import re
from typing import Any


def compact_json(value: Any, max_chars: int = 6000) -> str:
    """LLM prompt에 넣을 JSON context를 안전한 길이로 압축한다.

    state 전체나 검색 결과를 그대로 prompt에 넣으면 토큰 비용과 timeout 가능성이
    급격히 커진다. 호출부는 필요한 요약만 넘기고, 이 함수는 마지막 방어선으로
    JSON 직렬화와 길이 제한을 담당한다.
    """

    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def strip_json_fence(text: str) -> str:
    """모델이 붙인 ```json code fence를 제거한다.

    prompt는 JSON only를 요구하지만, 실제 모델은 종종 markdown fence를 붙인다.
    fence만 제거하고 본문은 그대로 둬서 뒤 단계가 순수 JSON 또는 설명 섞인 JSON을
    모두 처리할 수 있게 한다.
    """

    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def extract_json_object(text: str, *, object_name: str = "LLM response JSON") -> dict[str, Any]:
    """LLM 응답에서 JSON object 하나를 추출한다.

    1차로 응답 전체를 JSON으로 파싱하고, 실패하면 앞뒤 설명 사이에 들어간 첫 JSON
    object 후보를 찾아 다시 파싱한다. 최종 결과가 dict가 아니면 호출부가 deterministic
    fallback으로 넘어갈 수 있도록 명확한 예외를 발생시킨다.
    """

    cleaned = strip_json_fence(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))

    if not isinstance(payload, dict):
        raise ValueError(f"{object_name} must be an object")
    return payload
