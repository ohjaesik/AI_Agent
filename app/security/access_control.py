# app/security/access_control.py

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
    user_id: str = "local-user"
    role: str = DEFAULT_ROLE

    @property
    def normalized_role(self) -> str:
        return self.role if self.role in ROLE_MAX_LEVEL else DEFAULT_ROLE


def allowed_security_levels(role: str | None) -> list[str]:
    normalized_role = role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE
    max_level = ROLE_MAX_LEVEL[normalized_role]
    return [level for level, order in SECURITY_ORDER.items() if order <= max_level]


def can_access_security_level(role: str | None, security_level: str | None) -> bool:
    normalized_level = security_level or "internal"
    return normalized_level in allowed_security_levels(role)


def can_access_allowed_roles(role: str | None, allowed_roles: list[str] | None) -> bool:
    if not allowed_roles:
        return True
    normalized_role = role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE
    return normalized_role in allowed_roles or "admin" in {normalized_role}
