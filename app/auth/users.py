# app/auth/users.py

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
    id: int
    username: str
    role: str


def normalize_role(role: str | None) -> str:
    return role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
        return hmac.compare_digest(digest, expected_hex)
    except Exception:
        return False


def get_user_by_username(db: Session, username: str) -> AppUser | None:
    return db.execute(select(AppUser).where(AppUser.username == username)).scalars().first()


def create_user(db: Session, username: str, password: str, role: str = DEFAULT_ROLE) -> AppUser:
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
    user = get_user_by_username(db, username=username.strip())
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise ValueError("Invalid username or password.")
    return AuthenticatedUser(id=user.id, username=user.username, role=normalize_role(user.role))
