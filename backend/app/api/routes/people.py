"""Employees and user account administration."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.api.serializers import employee_to_read, user_to_read
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.permissions import permissions_for_role
from app.core.security import hash_password
from app.models import Employee, Role, User, UserSession
from app.schemas import (
    EmployeeCreate,
    EmployeeRead,
    EmployeeUpdate,
    Message,
    Page,
    PasswordResetRequest,
    RoleRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.audit import record_audit
from app.services.sequences import next_code

router = APIRouter(tags=["Personal y usuarios"])


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@router.get("/employees", response_model=Page[EmployeeRead], summary="Listar trabajadores")
def list_employees(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.WORKERS_READ)),
    search: str | None = None,
    status: str | None = None,
    department: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[EmployeeRead]:
    stmt = select(Employee)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Employee.code.ilike(term),
                Employee.first_name.ilike(term),
                Employee.last_name.ilike(term),
            )
        )
    if status:
        stmt = stmt.where(Employee.status == status)
    if department:
        stmt = stmt.where(Employee.department == department)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    employees = list(
        db.scalars(stmt.order_by(Employee.last_name, Employee.first_name).limit(limit).offset(offset)).all()
    )
    return Page(items=[employee_to_read(e) for e in employees], total=total, limit=limit, offset=offset)


@router.post("/employees", response_model=EmployeeRead, status_code=201, summary="Crear trabajador")
def create_employee(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.WORKERS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> EmployeeRead:
    employee = Employee(code=next_code(db, "employee"), **payload.model_dump())
    db.add(employee)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="employee.created",
        entity_type="employee",
        entity_id=employee.id,
        after={"code": employee.code, "name": employee.full_name, "department": employee.department},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(employee)
    return employee_to_read(employee)


@router.patch("/employees/{employee_id}", response_model=EmployeeRead, summary="Modificar trabajador")
def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.WORKERS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> EmployeeRead:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Trabajador", employee_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(employee, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="employee.updated",
        entity_type="employee",
        entity_id=employee.id,
        after=changes,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(employee)
    return employee_to_read(employee)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
@router.get("/roles", response_model=list[RoleRead], summary="Listar roles y nivel")
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.WORKERS_READ)),
) -> list[RoleRead]:
    roles = list(db.scalars(select(Role).order_by(Role.level)).all())
    return [
        RoleRead(
            id=role.id,
            code=role.code,
            name=role.name,
            level=role.level,
            description=role.description,
        )
        for role in roles
    ]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users", response_model=Page[UserRead], summary="Listar usuarios")
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    search: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[UserRead]:
    stmt = select(User)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(or_(User.email.ilike(term), User.full_name.ilike(term)))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    users = list(db.scalars(stmt.order_by(User.full_name).limit(limit).offset(offset)).all())
    return Page(items=[user_to_read(u) for u in users], total=total, limit=limit, offset=offset)


@router.post("/users", response_model=UserRead, status_code=201, summary="Crear usuario")
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> UserRead:
    email = payload.email.strip().lower()
    if "@" not in email:
        raise ValidationError("El correo electrónico no es válido.")
    if db.scalars(select(User).where(User.email == email)).first():
        raise ConflictError("Ya existe un usuario con ese correo.")
    role = db.scalars(select(Role).where(Role.level == payload.role_level)).first()
    if role is None:
        raise ValidationError("Nivel de rol no válido.")
    if payload.role_level < actor.role_level:
        raise ValidationError(
            "No puede crear un usuario con un nivel superior al suyo.",
            code="cannot_escalate_privileges",
        )
    employee = None
    if payload.employee_id:
        employee = db.get(Employee, payload.employee_id)
        if employee is None:
            raise NotFoundError("Trabajador", payload.employee_id)
        if employee.user_id:
            raise ConflictError("Ese trabajador ya tiene una cuenta asociada.")
    try:
        hashed = hash_password(payload.password)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hashed,
        role_id=role.id,
        must_change_password=payload.must_change_password,
    )
    db.add(user)
    db.flush()
    if employee:
        employee.user_id = user.id
    record_audit(
        db,
        actor_user_id=actor.id,
        actor_label=actor.full_name,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        after={"email": email, "role_level": role.level, "employee_id": payload.employee_id},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(user)
    return user_to_read(user)


@router.patch("/users/{user_id}", response_model=UserRead, summary="Modificar usuario")
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> UserRead:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("Usuario", user_id)
    changes = payload.model_dump(exclude_unset=True)

    if user.id == actor.id and ("role_level" in changes or changes.get("is_active") is False):
        raise ValidationError(
            "No puede cambiar su propio rol ni desactivar su propia cuenta.",
            code="self_modification_blocked",
        )
    if "role_level" in changes:
        if changes["role_level"] < actor.role_level:
            raise ValidationError(
                "No puede asignar un nivel superior al suyo.",
                code="cannot_escalate_privileges",
            )
        role = db.scalars(select(Role).where(Role.level == changes["role_level"])).first()
        if role is None:
            raise ValidationError("Nivel de rol no válido.")
        user.role_id = role.id
    if "full_name" in changes and changes["full_name"]:
        user.full_name = changes["full_name"]
    if "is_active" in changes and changes["is_active"] is not None:
        user.is_active = bool(changes["is_active"])
        if not user.is_active:
            user.token_version += 1
            db.execute(
                update(UserSession)
                .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )
    if "employee_id" in changes:
        new_employee_id = changes["employee_id"]
        if user.employee is not None and user.employee.id != new_employee_id:
            user.employee.user_id = None
        if new_employee_id:
            employee = db.get(Employee, new_employee_id)
            if employee is None:
                raise NotFoundError("Trabajador", new_employee_id)
            if employee.user_id and employee.user_id != user.id:
                raise ConflictError("Ese trabajador ya tiene una cuenta asociada.")
            employee.user_id = user.id
    record_audit(
        db,
        actor_user_id=actor.id,
        actor_label=actor.full_name,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        after={k: v for k, v in changes.items() if k != "password"},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(user)
    return user_to_read(user)


@router.post("/users/{user_id}/reset-password", response_model=Message, summary="Restablecer contraseña")
def reset_password(
    user_id: str,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Message:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("Usuario", user_id)
    if user.role_level < actor.role_level:
        raise ValidationError("No puede restablecer la contraseña de un usuario de nivel superior.")
    try:
        user.hashed_password = hash_password(payload.new_password)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    user.must_change_password = payload.must_change_password
    user.token_version += 1
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    record_audit(
        db,
        actor_user_id=actor.id,
        actor_label=actor.full_name,
        action="user.password_reset",
        entity_type="user",
        entity_id=user.id,
        after={"must_change_password": payload.must_change_password},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    return Message(message="Contraseña restablecida. Se han cerrado las sesiones del usuario.")


@router.get("/users/{user_id}/permissions", response_model=dict, summary="Permisos efectivos")
def user_permissions(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.USERS_MANAGE)),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("Usuario", user_id)
    return {
        "user_id": user.id,
        "role_level": user.role_level,
        "role": user.role.name,
        "permissions": sorted(permissions_for_role(db, user.role_id)),
    }
