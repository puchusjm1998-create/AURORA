"""Reglas de alerta y ciclo de vida de las alertas operativas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import AlertSeverity, AlertStatus, PermissionCode
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.models import Alert, AlertRule, User
from app.schemas import (
    AlertAction,
    AlertEvaluationResult,
    AlertMetricValue,
    AlertRead,
    AlertRuleCreate,
    AlertRuleRead,
    AlertRuleUpdate,
    Page,
)
from app.services.alerts import current_metrics, evaluate_rules
from app.services.audit import record_audit

router = APIRouter(prefix="/alerts", tags=["Alertas"])


def _rule(db: Session, rule_id: str) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise NotFoundError("Regla de alerta", rule_id)
    return rule


def _alert(db: Session, alert_id: str) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError("Alerta", alert_id)
    return alert


def _rule_read(rule: AlertRule) -> AlertRuleRead:
    return AlertRuleRead.model_validate(rule).model_copy(
        update={"creator_name": rule.creator.full_name if rule.creator else None}
    )


def _alert_read(alert: Alert) -> AlertRead:
    return AlertRead.model_validate(alert).model_copy(
        update={
            "rule_name": alert.rule.name if alert.rule else None,
            "metric": alert.rule.metric.value if alert.rule else None,
            "operator": alert.rule.operator.value if alert.rule else None,
            "acknowledger_name": alert.acknowledger.full_name if alert.acknowledger else None,
            "resolver_name": alert.resolver.full_name if alert.resolver else None,
        }
    )


def _audit(db: Session, entity: str, entity_id: str, user: User, meta: RequestMeta, action: str, **after) -> None:
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action=action,
        entity_type=entity,
        entity_id=entity_id,
        after=after or None,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )


@router.get("/rules", response_model=Page[AlertRuleRead], summary="Listar reglas de alerta")
def list_rules(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INCIDENTS_READ)),
    active: bool | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[AlertRuleRead]:
    stmt = select(AlertRule)
    if active is not None:
        stmt = stmt.where(AlertRule.is_active.is_(active))
    if search:
        stmt = stmt.where(AlertRule.name.ilike(f"%{search.strip()}%"))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(AlertRule.is_active.desc(), AlertRule.name).limit(limit).offset(offset)
    ).all()
    return Page(items=[_rule_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.post("/rules", response_model=AlertRuleRead, status_code=201, summary="Crear regla")
def create_rule(
    payload: AlertRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> AlertRuleRead:
    rule = AlertRule(
        name=payload.name,
        metric=payload.metric,
        operator=payload.operator,
        threshold=payload.threshold,
        severity=payload.severity,
        cooldown_minutes=payload.cooldown_minutes,
        notify_emails=payload.notify_emails,
        is_active=payload.is_active,
        created_by=user.id,
    )
    db.add(rule)
    db.flush()
    _audit(db, "alert_rule", rule.id, user, meta, "alert_rule.created",
           name=rule.name, metric=rule.metric.value, threshold=str(rule.threshold))
    db.commit()
    db.refresh(rule)
    return _rule_read(rule)


@router.patch("/rules/{rule_id}", response_model=AlertRuleRead, summary="Modificar regla")
def update_rule(
    rule_id: str,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> AlertRuleRead:
    rule = _rule(db, rule_id)
    merged = {
        "name": rule.name,
        "metric": rule.metric,
        "operator": rule.operator,
        "threshold": rule.threshold,
        "severity": rule.severity,
        "cooldown_minutes": rule.cooldown_minutes,
        "notify_emails": rule.notify_emails,
        "is_active": rule.is_active,
        **payload.model_dump(exclude_unset=True),
    }
    try:
        validated = AlertRuleCreate(**merged)
    except PydanticValidationError as exc:
        raise ValidationError(
            "La regla no es válida.",
            details={"fields": [{"field": ".".join(map(str, error["loc"])),
                                 "message": error["msg"]} for error in exc.errors()]},
        ) from exc
    for field, value in validated.model_dump().items():
        setattr(rule, field, value)
    _audit(db, "alert_rule", rule.id, user, meta, "alert_rule.updated",
           name=rule.name, threshold=str(rule.threshold), is_active=rule.is_active)
    db.commit()
    db.refresh(rule)
    return _rule_read(rule)


@router.delete("/rules/{rule_id}", status_code=204, summary="Eliminar regla sin alertas")
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> Response:
    rule = _rule(db, rule_id)
    if db.scalar(select(func.count()).select_from(Alert).where(Alert.rule_id == rule.id)):
        raise ConflictError(
            "La regla tiene alertas asociadas; desactívela en lugar de eliminarla.",
            code="rule_has_alerts",
        )
    _audit(db, "alert_rule", rule.id, user, meta, "alert_rule.deleted", name=rule.name)
    db.delete(rule)
    db.commit()
    return Response(status_code=204)


@router.get("", response_model=Page[AlertRead], summary="Listar alertas")
def list_alerts(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INCIDENTS_READ)),
    status: AlertStatus | None = None,
    severity: AlertSeverity | None = None,
    rule_id: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[AlertRead]:
    stmt = select(Alert).join(AlertRule, AlertRule.id == Alert.rule_id)
    if status is not None:
        stmt = stmt.where(Alert.status == status)
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity)
    if rule_id:
        stmt = stmt.where(Alert.rule_id == rule_id)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(or_(Alert.message.ilike(term), AlertRule.name.ilike(term)))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(Alert.triggered_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page(items=[_alert_read(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/metrics", response_model=list[AlertMetricValue], summary="Valores actuales")
def list_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INCIDENTS_READ)),
) -> list[AlertMetricValue]:
    return [AlertMetricValue(**item) for item in current_metrics(db)]


@router.post("/evaluate", response_model=AlertEvaluationResult, summary="Evaluar reglas ahora")
def evaluate_now(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> AlertEvaluationResult:
    result = evaluate_rules(db)
    alerts = result["alerts"]
    _audit(db, "alert_evaluation", "manual", user, meta, "alerts.evaluated",
           evaluated=result["evaluated"], triggered=result["triggered"])
    db.commit()
    return AlertEvaluationResult(
        evaluated=result["evaluated"],
        triggered=result["triggered"],
        skipped=result["skipped"],
        alerts=[_alert_read(alert) for alert in alerts],
    )


@router.post("/{alert_id}/acknowledge", response_model=AlertRead, summary="Reconocer alerta")
def acknowledge_alert(
    alert_id: str,
    payload: AlertAction | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> AlertRead:
    alert = _alert(db, alert_id)
    if alert.status != AlertStatus.OPEN:
        raise ConflictError(
            "Solo se pueden reconocer alertas abiertas.", code="invalid_transition"
        )
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by = user.id
    if payload and payload.note:
        alert.note = payload.note
    _audit(db, "alert", alert.id, user, meta, "alert.acknowledged",
           rule=alert.rule.name, note=alert.note)
    db.commit()
    db.refresh(alert)
    return _alert_read(alert)


@router.post("/{alert_id}/resolve", response_model=AlertRead, summary="Resolver alerta")
def resolve_alert(
    alert_id: str,
    payload: AlertAction | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.INCIDENTS_WRITE)),
    meta: RequestMeta = Depends(get_request_meta),
) -> AlertRead:
    alert = _alert(db, alert_id)
    if alert.status == AlertStatus.RESOLVED:
        raise ConflictError("La alerta ya está resuelta.", code="invalid_transition")
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = utcnow()
    alert.resolved_by = user.id
    if alert.acknowledged_at is None:
        alert.acknowledged_at = alert.resolved_at
        alert.acknowledged_by = user.id
    if payload and payload.note:
        alert.note = payload.note
    _audit(db, "alert", alert.id, user, meta, "alert.resolved",
           rule=alert.rule.name, note=alert.note)
    db.commit()
    db.refresh(alert)
    return _alert_read(alert)
