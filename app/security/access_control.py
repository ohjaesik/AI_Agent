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
    """AccessContext 클래스. 문서 보안 레벨과 사용자 role 기반 접근 제어 helper.에서 사용하는 구조화된 데이터/동작 단위다."""
    user_id: str = "local-user"
    role: str = DEFAULT_ROLE

    @property
    def normalized_role(self) -> str:
        """normalized_role 함수. 문서 보안 레벨과 사용자 role 기반 접근 제어 helper. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
        return self.role if self.role in ROLE_MAX_LEVEL else DEFAULT_ROLE


def allowed_security_levels(role: str | None) -> list[str]:
    """allowed_security_levels 함수. 문서 보안 레벨과 사용자 role 기반 접근 제어 helper. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    normalized_role = role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE
    max_level = ROLE_MAX_LEVEL[normalized_role]
    return [level for level, order in SECURITY_ORDER.items() if order <= max_level]


def can_access_security_level(role: str | None, security_level: str | None) -> bool:
    """can_access_security_level 함수. 문서 보안 레벨과 사용자 role 기반 접근 제어 helper. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    normalized_level = security_level or "internal"
    return normalized_level in allowed_security_levels(role)


def can_access_allowed_roles(role: str | None, allowed_roles: list[str] | None) -> bool:
    """can_access_allowed_roles 함수. 문서 보안 레벨과 사용자 role 기반 접근 제어 helper. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    if not allowed_roles:
        return True
    normalized_role = role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE
    return normalized_role in allowed_roles or "admin" in {normalized_role}
