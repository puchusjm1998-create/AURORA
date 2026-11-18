"""Authentication endpoints. Sessions are httpOnly cookies plus Bearer support."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import (
    RequestMeta,
    get_current_session,
    get_current_user,
    get_request_meta,
    get_user_permissions,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AuthError, RateLimitError, ValidationError
from app.core.security import (
    constant_time_dummy_verify,
    create_access_token,
    hash_password,
    login_limiter,
    new_session_id,
    rate_limit_key,
    validate_password_policy,
    verify_password,
)
from app.models import User, UserSession
from app.schemas import ChangePasswordRequest, LoginRequest, Message, UserMe
from app.api.serializers import employee_brief
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["Autenticación"])
settings = get_settings()


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _me_payload(db: Session, user: User) -> UserMe:
    return UserMe(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role_level=user.role_level,
        role_code=user.role.code,
        role_name=user.role.name,
        permissions=get_user_permissions(db, user),
        must_change_password=user.must_change_password,
        employee=employee_brief(user.employee),
    )


def _issue_session(db: Session, user: User, meta: RequestMeta) -> tuple[str, int]:
    jti = new_session_id()
    token, expires = create_access_token(
        user_id=user.id, role_level=user.role_level, token_version=user.token_version, jti=jti
    )
    session = UserSession(
        id=jti,
        user_id=user.id,
        expires_at=expires,
        ip=meta.ip,
        user_agent=(meta.user_agent or "")[:255] or None,
    )
    db.add(session)
    return token, int((expires - datetime.now(timezone.utc)).total_seconds())


@router.post("/login", response_model=UserMe, summary="Iniciar sesión")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    meta: RequestMeta = Depends(get_request_meta),
) -> UserMe:
    email = payload.email.strip().lower()
    limiter_key = rate_limit_key(meta.ip, email)
    if not login_limiter.allow(limiter_key):
        raise RateLimitError("Demasiados intentos de acceso. Espere unos minutos e inténtelo de nuevo.")

    user = db.scalars(select(User).where(User.email == email)).first()
    now = datetime.now(timezone.utc)
    if user is None:
        constant_time_dummy_verify()
        record_audit(
            db,
            actor_user_id=None,
            actor_label="anónimo",
            action="auth.login_failed",
            entity_type="user",
            entity_id=None,
            after={"email": email, "reason": "unknown_user"},
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
        db.commit()
        raise AuthError("Credenciales incorrectas.")

    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until and locked_until > now:
        raise RateLimitError("Cuenta bloqueada temporalmente por intentos fallidos. Contacte con el administrador.")

    if not verify_password(payload.password, user.hashed_password):
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            user.locked_until = now + timedelta(minutes=15)
            user.failed_login_count = 0
        record_audit(
            db,
            actor_user_id=None,
            actor_label="anónimo",
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            after={"email": email, "reason": "bad_password", "locked": bool(user.locked_until)},
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
        db.commit()
        raise AuthError("Credenciales incorrectas.")

    if not user.is_active:
        raise AuthError("La cuenta está desactivada. Contacte con el administrador.")

    login_limiter.reset(limiter_key)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    token, max_age = _issue_session(db, user, meta)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    _set_session_cookie(response, token, max_age)
    db.refresh(user)
    return _me_payload(db, user)


@router.post("/logout", response_model=Message, summary="Cerrar sesión")
def logout(
    response: Response,
    session_pair: tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    user, session = session_pair
    session.revoked_at = datetime.now(timezone.utc)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="auth.logout",
        entity_type="user_session",
        entity_id=session.id,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    return Message(message="Sesión cerrada correctamente.")


@router.post("/logout-all", response_model=Message, summary="Cerrar todas las sesiones")
def logout_all(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    now = datetime.now(timezone.utc)
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    user.token_version += 1
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="auth.logout_all",
        entity_type="user",
        entity_id=user.id,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    return Message(message="Todas las sesiones se han cerrado.")


@router.get("/me", response_model=UserMe, summary="Usuario autenticado")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserMe:
    return _me_payload(db, user)


@router.post("/change-password", response_model=Message, summary="Cambiar contraseña")
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    session_pair: tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    user, current_session = session_pair
    if not verify_password(payload.current_password, user.hashed_password):
        raise ValidationError("La contraseña actual no es correcta.", code="invalid_current_password")
    try:
        validate_password_policy(payload.new_password)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if verify_password(payload.new_password, user.hashed_password):
        raise ValidationError("La nueva contraseña debe ser distinta de la actual.")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    user.token_version += 1
    now = datetime.now(timezone.utc)
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.id != current_session.id,
        )
        .values(revoked_at=now)
    )
    current_session.revoked_at = now
    token, max_age = _issue_session(db, user, meta)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="auth.password_changed",
        entity_type="user",
        entity_id=user.id,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    _set_session_cookie(response, token, max_age)
    return Message(message="Contraseña actualizada. Las demás sesiones se han cerrado.")
