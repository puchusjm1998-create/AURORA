"""Request dependencies: authentication, session validation and RBAC guards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import AuthError, PermissionDeniedError
from app.core.permissions import permissions_for_role
from app.core.security import decode_access_token
from app.models import User, UserSession

settings = get_settings()


@dataclass
class RequestMeta:
    ip: str | None
    user_agent: str | None


def get_request_meta(request: Request) -> RequestMeta:
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return RequestMeta(ip=ip, user_agent=request.headers.get("user-agent"))


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = request.cookies.get(settings.cookie_name)
    if token:
        return token
    raise AuthError("Sesión no válida o expirada. Inicie sesión de nuevo.")


def get_current_session(request: Request, db: Session = Depends(get_db)) -> tuple[User, UserSession]:
    token = _extract_token(request)
    try:
        payload = decode_access_token(token)
    except Exception as exc:  # jwt.ExpiredSignatureError / InvalidTokenError
        raise AuthError("Sesión no válida o expirada. Inicie sesión de nuevo.") from exc

    session = db.get(UserSession, payload.get("jti", ""))
    if session is None or session.revoked_at is not None:
        raise AuthError("La sesión ha sido revocada. Inicie sesión de nuevo.")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AuthError("La sesión ha caducado. Inicie sesión de nuevo.")

    user = db.get(User, payload.get("sub", ""))
    if user is None or not user.is_active:
        raise AuthError("Usuario no autorizado.")
    if int(payload.get("ver", 0)) != user.token_version:
        raise AuthError("Sesión invalidada por un cambio de seguridad.")

    return user, session


def get_current_user(
    session_pair: tuple[User, UserSession] = Depends(get_current_session),
) -> User:
    return session_pair[0]


def require_permissions(*required: PermissionCode) -> Callable:
    """Guard that checks permissions on the server for the authenticated role."""

    def dependency(
        user: User = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> User:
        granted = permissions_for_role(db, user.role_id)
        missing = [code.value for code in required if code.value not in granted]
        if missing:
            raise PermissionDeniedError(
                "No dispone de permisos para esta operación.",
                details={"missing_permissions": missing},
            )
        return user

    return dependency


def require_permission(permission: PermissionCode) -> Callable:
    return require_permissions(permission)


def require_max_level(max_level: int) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role_level > max_level:
            raise PermissionDeniedError(
                "Esta operación requiere un nivel de autorización superior.",
                code="insufficient_authority",
                details={"required_max_level": max_level, "actual_level": user.role_level},
            )
        return user

    return dependency


def require_any_permission(*required: PermissionCode) -> Callable:
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        granted = permissions_for_role(db, user.role_id)
        if not any(code.value in granted for code in required):
            raise PermissionDeniedError(
                "No dispone de permisos para esta operación.",
                details={"any_of": [c.value for c in required]},
            )
        return user

    return dependency


def get_user_permissions(db: Session, user: User) -> list[str]:
    return sorted(permissions_for_role(db, user.role_id))


def ensure_employee_access(db: Session, user: User, employee_id: str) -> None:
    """Level 4 workers may only act on their own employee record."""
    if user.role_level <= 3:
        return
    employee = user.employee
    if employee is None or employee.id != employee_id:
        raise PermissionDeniedError("Solo puede operar sobre su propia ficha de trabajador.")


def user_is_active(user: User) -> bool:
    return user.is_active


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(User.email == email.lower().strip())).first()
