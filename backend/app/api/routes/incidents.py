"""Warehouse incidents: reporting, triage and resolution.

An incident documents something that went wrong (damage, stock discrepancy,
quality or safety issue) and how it was resolved. It never changes stock by
itself: corrections are made through audited movements, so the ledger remains
the only explanation of physical quantities.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_any_permission, require_permission
from app.core.db import get_db
from app.core.enums import (
    EmployeeStatus,
    IncidentSeverity,
    IncidentStatus,
    PermissionCode,
)
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.models import Employee, Incident, Location, Pallet, Product, User
from app.schemas import (
    IncidentCreate,
    IncidentRead,
    IncidentResolve,
    IncidentUpdate,
    Page,
)
from app.services.audit import record_audit
from app.services.sequences import next_code

router = APIRouter(prefix="/incidents", tags=["Incidencias"])

OPEN_STATUSES = (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED)


def _to_read(incident: Incident) -> IncidentRead:
    employee = incident.assignee
    return IncidentRead(
        id=incident.id,
        code=incident.code,
        title=incident.title,
        description=incident.description,
        incident_type=incident.incident_type,
        severity=incident.severity,
        status=incident.status,
        location_id=incident.location_id,
        location_code=incident.location.full_code if incident.location else None,
        product_id=incident.product_id,
        product_sku=incident.product.sku if incident.product else None,
        product_name=incident.product.name if incident.product else None,
        pallet_id=incident.pallet_id,
        pallet_code=incident.pallet.code if incident.pallet else None,
        reported_by_name=incident.reporter.full_name if incident.reporter else None,
        assigned_to=incident.assigned_to,
        assignee_name=employee.full_name if employee else None,
        assignee_code=employee.code if employee else None,
        resolution=incident.resolution,
        resolved_at=incident.resolved_at,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


def _get_incident(db: Session, incident_id: str) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError("Incidencia", incident_id)
    return incident


def _check_employee(db: Session, employee_id: str | None) -> None:
    if not employee_id:
        return
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Trabajador", employee_id)
    if employee.status == EmployeeStatus.INACTIVE:
        raise ValidationError("No se puede asignar una incidencia a un trabajador inactivo.")


def _check_refs(db: Session, *, location_id: str | None, product_id: str | None, pallet_id: str | None) -> None:
    if location_id and db.get(Location, location_id) is None:
        raise NotFoundError("Ubicación", location_id)
    if product_id and db.get(Product, product_id) is None:
        raise NotFoundError("Producto", product_id)
    if pallet_id and db.get(Pallet, pallet_id) is None:
        raise NotFoundError("Palé", pallet_id)


def _audit(db: Session, incident: Incident, user: User, meta: RequestMeta, action: str, **before) -> None:
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action=action,
        entity_type="incident",
        entity_id=incident.id,
        before=before or None,
        after={"status": incident.status.value, "severity": incident.severity.value},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )


@router.get("", response_model=Page[IncidentRead], summary="Listar incidencias")
def list_incidents(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INCIDENTS_READ)),
    status: str | None = None,
    severity: str | None = None,
    incident_type: str | None = None,
    assigned_to: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[IncidentRead]:
    stmt = select(Incident)
    if status:
        values = [value.strip() for value in status.split(",") if value.strip()]
        stmt = stmt.where(Incident.status.in_(values))
    if severity:
        values = [value.strip() for value in severity.split(",") if value.strip()]
        stmt = stmt.where(Incident.severity.in_(values))
    if incident_type:
        stmt = stmt.where(Incident.incident_type == incident_type)
    if assigned_to:
        stmt = stmt.where(Incident.assigned_to == assigned_to)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Incident.code.ilike(term),
                Incident.title.ilike(term),
                Incident.description.ilike(term),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(
                case(
                    (Incident.status == IncidentStatus.OPEN, 0),
                    (Incident.status == IncidentStatus.ACKNOWLEDGED, 1),
                    (Incident.status == IncidentStatus.RESOLVED, 2),
                    else_=3,
                ),
                case(
                    (Incident.severity == IncidentSeverity.CRITICAL, 0),
                    (Incident.severity == IncidentSeverity.HIGH, 1),
                    (Incident.severity == IncidentSeverity.MEDIUM, 2),
                    else_=3,
                ),
                Incident.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return Page(items=[_to_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/{incident_id}", response_model=IncidentRead, summary="Detalle de incidencia")
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INCIDENTS_READ)),
) -> IncidentRead:
    return _to_read(_get_incident(db, incident_id))


@router.post("", response_model=IncidentRead, status_code=201, summary="Registrar incidencia")
def create_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_any_permission(PermissionCode.INCIDENTS_WRITE, PermissionCode.INCIDENTS_REPORT)
    ),
    meta: RequestMeta = Depends(get_request_meta),
) -> IncidentRead:
    _check_employee(db, payload.assigned_to)
    _check_refs(
        db,
        location_id=payload.location_id,
        product_id=payload.product_id,
        pallet_id=payload.pallet_id,
    )
    incident = Incident(
        code=next_code(db, "incident"),
        title=payload.title.strip(),
        description=payload.description.strip(),
        incident_type=payload.incident_type,
        severity=payload.severity,
        reported_by=user.id,
        assigned_to=payload.assigned_to,
        location_id=payload.location_id,
        product_id=payload.product_id,
        pallet_id=payload.pallet_id,
    )
    db.add(incident)
    db.flush()
    _audit(db, incident, user, meta, "incident.created")
    db.commit()
    db.refresh(incident)
    return _to_read(incident)


@router.patch("/{incident_id}", response_model=IncidentRead, summary="Editar incidencia")
def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> IncidentRead:
    incident = _get_incident(db, incident_id)
    if incident.status == IncidentStatus.CLOSED:
        raise ConflictError("La incidencia está cerrada y no se puede editar.", code="incident_closed")
    changes = payload.model_dump(exclude_unset=True)
    if "assigned_to" in changes:
        _check_employee(db, changes["assigned_to"])
    _check_refs(
        db,
        location_id=changes.get("location_id"),
        product_id=changes.get("product_id"),
        pallet_id=changes.get("pallet_id"),
    )
    before = {key: getattr(incident, key) for key in changes if key in {"title", "severity", "status"}}
    for key, value in changes.items():
        if key == "title" and value is not None:
            value = value.strip()
        if key == "description" and value is not None:
            value = value.strip()
        setattr(incident, key, value)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="incident.updated",
        entity_type="incident",
        entity_id=incident.id,
        before={k: str(v) for k, v in before.items()},
        after={"fields": sorted(changes.keys())},
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    db.commit()
    db.refresh(incident)
    return _to_read(incident)


@router.post("/{incident_id}/acknowledge", response_model=IncidentRead, summary="Reconocer incidencia")
def acknowledge_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> IncidentRead:
    incident = _get_incident(db, incident_id)
    if incident.status != IncidentStatus.OPEN:
        raise ConflictError(
            "Solo se pueden reconocer incidencias abiertas.", code="invalid_transition"
        )
    previous = incident.status
    incident.status = IncidentStatus.ACKNOWLEDGED
    _audit(db, incident, user, meta, "incident.acknowledged", status=previous.value)
    db.commit()
    db.refresh(incident)
    return _to_read(incident)


@router.post("/{incident_id}/resolve", response_model=IncidentRead, summary="Resolver incidencia")
def resolve_incident(
    incident_id: str,
    payload: IncidentResolve,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> IncidentRead:
    incident = _get_incident(db, incident_id)
    if incident.status not in OPEN_STATUSES:
        raise ConflictError(
            "Solo se pueden resolver incidencias abiertas o reconocidas.", code="invalid_transition"
        )
    resolution = payload.resolution.strip()
    if len(resolution) < 5:
        raise ValidationError("La resolución debe explicar qué se hizo (mínimo 5 caracteres).")
    previous = incident.status
    incident.status = IncidentStatus.RESOLVED
    incident.resolution = resolution
    incident.resolved_at = utcnow()
    _audit(db, incident, user, meta, "incident.resolved", status=previous.value)
    db.commit()
    db.refresh(incident)
    return _to_read(incident)


@router.post("/{incident_id}/close", response_model=IncidentRead, summary="Cerrar incidencia")
def close_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> IncidentRead:
    incident = _get_incident(db, incident_id)
    if incident.status != IncidentStatus.RESOLVED:
        raise ConflictError(
            "Solo se pueden cerrar incidencias resueltas.", code="invalid_transition"
        )
    incident.status = IncidentStatus.CLOSED
    _audit(db, incident, user, meta, "incident.closed", status="resolved")
    db.commit()
    db.refresh(incident)
    return _to_read(incident)


@router.post("/{incident_id}/reopen", response_model=IncidentRead, summary="Reabrir incidencia")
def reopen_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> IncidentRead:
    incident = _get_incident(db, incident_id)
    if incident.status not in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
        raise ConflictError(
            "Solo se pueden reabrir incidencias resueltas o cerradas.", code="invalid_transition"
        )
    previous = incident.status
    incident.status = IncidentStatus.OPEN
    incident.resolved_at = None
    incident.resolution = ""
    _audit(db, incident, user, meta, "incident.reopened", status=previous.value)
    db.commit()
    db.refresh(incident)
    return _to_read(incident)
