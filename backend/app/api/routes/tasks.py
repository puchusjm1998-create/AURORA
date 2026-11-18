"""Warehouse tasks: planning, assignment and human completion.

Tasks are intentionally simple and auditable: creating, assigning, starting and
completing are separate, permission-checked actions. A worker with level 4 can
only start/complete tasks assigned to their own employee record; supervisors
(level 3 and above) can operate on any task.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import EmployeeStatus, PermissionCode, TaskStatus
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.timeutils import utcnow
from app.models import Employee, Task, User
from app.schemas import Page, TaskCreate, TaskRead, TaskUpdate
from app.services.audit import record_audit
from app.services.sequences import next_code

router = APIRouter(prefix="/tasks", tags=["Tareas"])

OPEN_STATUSES = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)


def _to_read(task: Task) -> TaskRead:
    employee = task.assigned_employee
    return TaskRead(
        id=task.id,
        code=task.code,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        assigned_to=task.assigned_to,
        assignee_name=employee.full_name if employee else None,
        assignee_code=employee.code if employee else None,
        created_by_name=task.creator.full_name if task.creator else "",
        due_at=task.due_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
    )


def _get_task(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundError("Tarea", task_id)
    return task


def _employee_for_assignment(db: Session, employee_id: str | None) -> Employee | None:
    if not employee_id:
        return None
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Trabajador", employee_id)
    if employee.status == EmployeeStatus.INACTIVE:
        raise ValidationError("No se puede asignar una tarea a un trabajador inactivo.")
    return employee


def _ensure_can_execute(user: User, task: Task) -> None:
    """Level 4 workers may only execute tasks assigned to their own employee."""
    if user.role_level < 4:
        return
    own_employee = user.employee.id if user.employee else None
    if not own_employee or task.assigned_to != own_employee:
        raise PermissionDeniedError("Solo puede iniciar o completar tareas asignadas a usted.")


@router.get("", response_model=Page[TaskRead], summary="Listar tareas")
def list_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.TASKS_READ)),
    status: str | None = None,
    assigned_to: str | None = None,
    mine: bool = False,
    priority: int | None = Query(None, ge=1, le=5),
    search: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[TaskRead]:
    stmt = select(Task)
    if status:
        statuses = [value.strip() for value in status.split(",") if value.strip()]
        stmt = stmt.where(Task.status.in_(statuses))
    target_employee = assigned_to
    if mine:
        target_employee = user.employee.id if user.employee else ""
    if target_employee:
        stmt = stmt.where(Task.assigned_to == target_employee)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Task.code.ilike(term), Task.title.ilike(term), Task.description.ilike(term))
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(
                case(
                    (Task.status == TaskStatus.IN_PROGRESS, 0),
                    (Task.status == TaskStatus.PENDING, 1),
                    (Task.status == TaskStatus.BLOCKED, 2),
                    else_=3,
                ),
                Task.priority,
                Task.due_at,
                Task.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return Page(items=[_to_read(task) for task in rows], total=total, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskRead, summary="Consultar tarea")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.TASKS_READ)),
) -> TaskRead:
    return _to_read(_get_task(db, task_id))


@router.post("", response_model=TaskRead, status_code=201, summary="Crear tarea")
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.TASKS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> TaskRead:
    if not payload.title.strip():
        raise ValidationError("El título de la tarea es obligatorio.")
    _employee_for_assignment(db, payload.assigned_to)
    task = Task(
        code=next_code(db, "task"),
        title=payload.title.strip(),
        description=payload.description.strip(),
        priority=payload.priority,
        assigned_to=payload.assigned_to,
        due_at=payload.due_at,
        created_by=user.id,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        after={
            "code": task.code,
            "title": task.title,
            "priority": task.priority,
            "assigned_to": task.assigned_to,
            "due_at": task.due_at.isoformat() if task.due_at else None,
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(task)
    return _to_read(task)


@router.patch("/{task_id}", response_model=TaskRead, summary="Modificar tarea")
def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.TASKS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> TaskRead:
    task = _get_task(db, task_id)
    if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        raise ConflictError("Reabra la tarea antes de modificarla.", code="task_closed")
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        if not changes["title"] or not changes["title"].strip():
            raise ValidationError("El título de la tarea es obligatorio.")
        changes["title"] = changes["title"].strip()
    if "description" in changes and changes["description"] is not None:
        changes["description"] = changes["description"].strip()
    if "assigned_to" in changes:
        _employee_for_assignment(db, changes["assigned_to"])
    before = {
        key: getattr(task, key).isoformat() if hasattr(getattr(task, key), "isoformat") else getattr(task, key)
        for key in changes
    }
    for field, value in changes.items():
        setattr(task, field, value)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="task.updated",
        entity_type="task",
        entity_id=task.id,
        before=before,
        after={
            key: getattr(task, key).isoformat()
            if hasattr(getattr(task, key), "isoformat")
            else getattr(task, key)
            for key in changes
        },
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(task)
    return _to_read(task)


@router.post("/{task_id}/start", response_model=TaskRead, summary="Iniciar tarea")
def start_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.TASKS_COMPLETE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> TaskRead:
    task = _get_task(db, task_id)
    _ensure_can_execute(user, task)
    if task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
        raise ConflictError("La tarea no se puede iniciar en su estado actual.", code="invalid_transition")
    previous = task.status
    task.status = TaskStatus.IN_PROGRESS
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="task.started",
        entity_type="task",
        entity_id=task.id,
        before={"status": previous.value},
        after={"status": task.status.value},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(task)
    return _to_read(task)


@router.post("/{task_id}/complete", response_model=TaskRead, summary="Completar tarea")
def complete_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.TASKS_COMPLETE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> TaskRead:
    task = _get_task(db, task_id)
    _ensure_can_execute(user, task)
    if task.status not in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
        raise ConflictError("La tarea no se puede completar en su estado actual.", code="invalid_transition")
    previous = task.status
    task.status = TaskStatus.DONE
    task.completed_at = utcnow()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="task.completed",
        entity_type="task",
        entity_id=task.id,
        before={"status": previous.value},
        after={"status": task.status.value, "completed_at": task.completed_at.isoformat()},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(task)
    return _to_read(task)


@router.post("/{task_id}/cancel", response_model=TaskRead, summary="Cancelar tarea")
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.TASKS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> TaskRead:
    task = _get_task(db, task_id)
    if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        raise ConflictError("La tarea ya está cerrada.", code="task_closed")
    previous = task.status
    task.status = TaskStatus.CANCELLED
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="task.cancelled",
        entity_type="task",
        entity_id=task.id,
        before={"status": previous.value},
        after={"status": task.status.value},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(task)
    return _to_read(task)


@router.post("/{task_id}/reopen", response_model=TaskRead, summary="Reabrir tarea")
def reopen_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.TASKS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> TaskRead:
    task = _get_task(db, task_id)
    if task.status not in (TaskStatus.DONE, TaskStatus.CANCELLED):
        raise ConflictError("Solo se pueden reabrir tareas cerradas.", code="invalid_transition")
    previous = task.status
    task.status = TaskStatus.PENDING
    task.completed_at = None
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="task.reopened",
        entity_type="task",
        entity_id=task.id,
        before={"status": previous.value},
        after={"status": task.status.value},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(task)
    return _to_read(task)
