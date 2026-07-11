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
    """AuthenticatedUser 클래스. 로컬 사용자 계정 생성과 비밀번호 검증 로직.에서 사용하는 구조화된 데이터/동작 단위다."""
    id: int
    username: str
    role: str


def normalize_role(role: str | None) -> str:
    """normalize_role 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    return role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE


def hash_password(password: str) -> str:
    """hash_password 함수. 로컬 사용자 계정 생성과 비밀번호 검증 로직. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """verify_password 함수. 로컬 사용자 계정 생성과 비밀번호 검증 로직. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    try:
        algorithm, iterations, salt, expected_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
        return hmac.compare_digest(digest, expected_hex)
    except Exception:
        return False


def get_user_by_username(db: Session, username: str) -> AppUser | None:
    """get_user_by_username 함수. DB나 설정/state에서 필요한 값을 조회해 호출자에게 반환한다."""
    return db.execute(select(AppUser).where(AppUser.username == username)).scalars().first()


def create_user(db: Session, username: str, password: str, role: str = DEFAULT_ROLE) -> AppUser:
    """create_user 함수. DB record 또는 domain 객체를 생성하고 필요한 기본값/관계를 함께 설정한다."""
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
    """authenticate_user 함수. 로컬 사용자 계정 생성과 비밀번호 검증 로직. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    user = get_user_by_username(db, username=username.strip())
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise ValueError("Invalid username or password.")
    return AuthenticatedUser(id=user.id, username=user.username, role=normalize_role(user.role))
