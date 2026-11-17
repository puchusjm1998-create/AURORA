"""Authentication primitives: password hashing, JWT issuing/validation, rate limiting."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()

MIN_PASSWORD_LENGTH = 10


class PasswordPolicyError(ValueError):
    pass


def validate_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
    if len(password.encode("utf-8")) > 72:
        raise PasswordPolicyError("La contraseña no puede superar 72 bytes.")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise PasswordPolicyError("La contraseña debe incluir letras y números.")


def hash_password(password: str) -> str:
    validate_password_policy(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(*, user_id: str, role_level: int, token_version: int, jti: str) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "jti": jti,
        "lvl": role_level,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": "aurora-logistics-ai",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        issuer="aurora-logistics-ai",
        options={"require": ["sub", "jti", "exp", "iat"]},
    )


def new_session_id() -> str:
    return str(uuid.uuid4())


def token_fingerprint(token: str) -> str:
    """Non-reversible fingerprint used only for audit correlation."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


class SlidingWindowLimiter:
    """In-process sliding-window limiter.

    Suitable for a single API instance; for multi-instance deployments the same
    interface must be backed by Redis (documented in docs/DEPLOYMENT.md).
    """

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def reset_all(self) -> None:
        with self._lock:
            self._hits.clear()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_attempts:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


login_limiter = SlidingWindowLimiter(settings.login_max_attempts, settings.login_window_seconds)


def rate_limit_key(ip: str | None, email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:12]
    return f"{ip or 'unknown'}:{digest}"


def constant_time_dummy_verify() -> None:
    """Burn comparable time when a user does not exist (user enumeration defence)."""
    secrets.compare_digest("aurora-dummy", "aurora-dummy")
    bcrypt.hashpw(b"aurora-dummy-password", bcrypt.gensalt(rounds=4))
