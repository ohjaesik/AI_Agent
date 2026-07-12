# app/security/access_control.py

"""문서 보안 레벨과 사용자 role 기반 접근 제어 helper.

RAG 검색 시 어떤 security_level 문서를 볼 수 있는지 결정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

SECURITY_ORDER = {
    "public": 0,
    "public_official": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}

ROLE_MAX_LEVEL = {
    "viewer": 0,
    "analyst": 1,
    "manager": 2,
    "admin": 3,
}

DEFAULT_ROLE = "analyst"


@dataclass(frozen=True)
class AccessContext:
    """현재 요청 사용자의 id와 role을 담아 RAG/문서 조회 권한 판단에 넘기는 값 객체다."""
    user_id: str = "local-user"
    role: str = DEFAULT_ROLE

    @property
    def normalized_role(self) -> str:
        """알 수 없는 role이면 DEFAULT_ROLE로 낮춰 권한이 과도하게 열리지 않게 한다."""
        return self.role if self.role in ROLE_MAX_LEVEL else DEFAULT_ROLE


def allowed_security_levels(role: str | None) -> list[str]:
    """role이 읽을 수 있는 security_level 목록을 낮은 등급부터 모두 반환한다."""
    normalized_role = role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE
    max_level = ROLE_MAX_LEVEL[normalized_role]
    return [level for level, order in SECURITY_ORDER.items() if order <= max_level]


def can_access_security_level(role: str | None, security_level: str | None) -> bool:
    """문서 security_level이 사용자 role의 최대 허용 등급 안에 있는지 판단한다."""
    normalized_level = security_level or "internal"
    return normalized_level in allowed_security_levels(role)


def can_access_allowed_roles(role: str | None, allowed_roles: list[str] | None) -> bool:
    """문서별 allowed_roles 제한이 있을 때 현재 role이 포함되는지 확인한다."""
    if not allowed_roles:
        return True
    normalized_role = role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE
    return normalized_role in allowed_roles or "admin" in {normalized_role}
