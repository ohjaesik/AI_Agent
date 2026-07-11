"""LangGraph node가 공통으로 사용하는 audit/error trace helper.

DB audit log는 `app.db.crud.write_audit_log`가 담당하고, 이 모듈은 workflow state 안에
남기는 in-memory trace를 만든다. 각 node가 같은 형태의 `audit_logs`와 `errors`를
반환해야 UI/API/디버깅에서 단계별 실행 흐름을 일관되게 볼 수 있다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.graph.state import AXPlannerState


def utc_now() -> str:
    """UTC ISO timestamp를 생성해 audit log의 공통 시간값으로 사용한다."""

    return datetime.now(timezone.utc).isoformat()


def append_audit(
    state: AXPlannerState,
    node_name: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """현재 state의 audit_logs 뒤에 node 실행 기록을 하나 추가한다.

    LangGraph reducer가 list를 병합하더라도 각 node는 자신이 만든 변경분을 명확히
    반환해야 한다. 이 함수는 기존 audit를 유지하면서 node 이름, 성공/실패 상태,
    UTC timestamp, 요약 payload를 표준 형식으로 붙인다.
    """

    return state.get("audit_logs", []) + [
        {
            "node": node_name,
            "status": status,
            "timestamp": utc_now(),
            "payload": payload or {},
        }
    ]


def append_error(
    state: AXPlannerState,
    node_name: str,
    error: Exception,
) -> list[str]:
    """현재 state의 errors 뒤에 node명과 예외 타입을 포함한 오류 문자열을 추가한다."""

    return state.get("errors", []) + [
        f"[{node_name}] {type(error).__name__}: {str(error)}"
    ]
