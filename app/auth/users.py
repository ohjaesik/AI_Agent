# app/auth/users.py

"""로컬 사용자 계정 생성과 비밀번호 검증 로직.

운영형 IAM이 없는 로컬/데모 환경에서 admin/manager/analyst 계정을 DB에 저장하고
로그인 시 password hash를 검증한다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.security.access_control import DEFAULT_ROLE, ROLE_MAX_LEVEL

PBKDF2_ITERATIONS = 260_000


@dataclass(frozen=True)
class AuthenticatedUser:
    """인증을 통과한 사용자 정보를 API dependency가 넘겨받는 간단한 값 객체다."""
    id: int
    username: str
    role: str


def normalize_role(role: str | None) -> str:
    """normalize_role 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    return role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE


def hash_password(password: str) -> str:
    """비밀번호를 salt가 포함된 PBKDF2-SHA256 문자열로 변환해 DB 저장용으로 만든다."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """입력 비밀번호를 저장된 PBKDF2 hash와 constant-time 방식으로 비교한다."""
    try:
        algorithm, iterations, salt, expected_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
        return hmac.compare_digest(digest, expected_hex)
    except Exception:
        return False


def get_user_by_username(db: Session, username: str) -> AppUser | None:
    """username으로 활성 여부 확인 전의 AppUser row를 조회한다."""
    return db.execute(select(AppUser).where(AppUser.username == username)).scalars().first()


def create_user(db: Session, username: str, password: str, role: str = DEFAULT_ROLE) -> AppUser:
    """로컬 사용자 row를 생성하고 role 정규화와 비밀번호 hash 저장을 함께 처리한다."""
    user = AppUser(username=username.strip(), password_hash=hash_password(password), role=normalize_role(role), is_active=True)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError(f"User already exists: {username}") from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> AuthenticatedUser:
    """username/password를 검증하고 API에서 사용할 AuthenticatedUser로 축약한다."""
    user = get_user_by_username(db, username=username.strip())
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise ValueError("Invalid username or password.")
    return AuthenticatedUser(id=user.id, username=user.username, role=normalize_role(user.role))
