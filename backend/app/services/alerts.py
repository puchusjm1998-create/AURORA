"""Evaluación de reglas de alerta contra indicadores operativos reales."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import (
    AlertMetric,
    AlertOperator,
    AlertSeverity,
    AlertStatus,
    DeliveryStatus,
    IncidentStatus,
    ReservationStatus,
    TaskStatus,
)
from app.core.timeutils import utcnow
from app.models import (
    Alert,
    AlertRule,
    Delivery,
    Incident,
    Product,
    StockLevel,
    StockReservation,
    Task,
)
from app.services.audit import record_audit
from app.services.mailer import Message, send as send_mail

logger = logging.getLogger("aurora.alerts")

OPEN_TASKS = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)
OPEN_INCIDENTS = (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED)
PENDING_DELIVERIES = (
    DeliveryStatus.DRAFT,
    DeliveryStatus.PREPARING,
    DeliveryStatus.READY,
    DeliveryStatus.LOADED,
    DeliveryStatus.IN_TRANSIT,
)

OPERATOR_SYMBOLS = {
    AlertOperator.GT: ">",
    AlertOperator.GTE: ">=",
    AlertOperator.LT: "<",
    AlertOperator.LTE: "<=",
}

SEVERITY_LABELS = {
    AlertSeverity.INFO: "Informativa",
    AlertSeverity.WARNING: "Advertencia",
    AlertSeverity.CRITICAL: "Crítica",
}

Provider = Callable[[Session, datetime], Decimal]


@dataclass(frozen=True)
class MetricDefinition:
    code: AlertMetric
    label: str
    unit: str
    provider: Provider


def _open_tasks(db: Session, now: datetime) -> Decimal:
    return Decimal(
        db.scalar(select(func.count()).select_from(Task).where(Task.status.in_(OPEN_TASKS))) or 0
    )


def _overdue_tasks(db: Session, now: datetime) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.status.in_(OPEN_TASKS), Task.due_at.is_not(None), Task.due_at < now)
        )
        or 0
    )


def _open_incidents(db: Session, now: datetime) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status.in_(OPEN_INCIDENTS))
        )
        or 0
    )


def _active_reservations(db: Session, now: datetime) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.count())
            .select_from(StockReservation)
            .where(StockReservation.status == ReservationStatus.ACTIVE)
        )
        or 0
    )


def _pending_deliveries(db: Session, now: datetime) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.count())
            .select_from(Delivery)
            .where(Delivery.status.in_(PENDING_DELIVERIES))
        )
        or 0
    )


def _low_stock_products(db: Session, now: datetime) -> Decimal:
    totals = (
        select(StockLevel.product_id, func.sum(StockLevel.quantity).label("qty"))
        .group_by(StockLevel.product_id)
        .subquery()
    )
    stmt = (
        select(func.count())
        .select_from(Product)
        .outerjoin(totals, totals.c.product_id == Product.id)
        .where(func.coalesce(totals.c.qty, 0) < Product.min_stock)
    )
    return Decimal(db.scalar(stmt) or 0)


def _stock_units(db: Session, now: datetime) -> Decimal:
    return Decimal(str(db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0))) or 0))


METRICS: dict[AlertMetric, MetricDefinition] = {
    definition.code: definition
    for definition in [
        MetricDefinition(AlertMetric.OPEN_TASKS, "Tareas abiertas", "tareas", _open_tasks),
        MetricDefinition(AlertMetric.OVERDUE_TASKS, "Tareas vencidas", "tareas", _overdue_tasks),
        MetricDefinition(AlertMetric.OPEN_INCIDENTS, "Incidencias abiertas", "incidencias", _open_incidents),
        MetricDefinition(AlertMetric.ACTIVE_RESERVATIONS, "Reservas activas", "reservas", _active_reservations),
        MetricDefinition(AlertMetric.PENDING_DELIVERIES, "Repartos pendientes", "repartos", _pending_deliveries),
        MetricDefinition(AlertMetric.LOW_STOCK_PRODUCTS, "Productos bajo mínimo", "productos", _low_stock_products),
        MetricDefinition(AlertMetric.STOCK_UNITS, "Unidades en stock", "unidades", _stock_units),
    ]
}


def metric_value(db: Session, metric: AlertMetric, now: datetime | None = None) -> Decimal:
    moment = _as_utc(now or utcnow())
    return METRICS[metric].provider(db, moment)


def current_metrics(db: Session, now: datetime | None = None) -> list[dict[str, object]]:
    moment = _as_utc(now or utcnow())
    return [
        {
            "metric": definition.code,
            "label": definition.label,
            "unit": definition.unit,
            "value": definition.provider(db, moment),
        }
        for definition in METRICS.values()
    ]


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def matches(value: Decimal, operator: AlertOperator, threshold: Decimal) -> bool:
    if operator == AlertOperator.GT:
        return value > threshold
    if operator == AlertOperator.GTE:
        return value >= threshold
    if operator == AlertOperator.LT:
        return value < threshold
    return value <= threshold


def _format_value(value: Decimal) -> str:
    return f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}"


def alert_message(rule: AlertRule, value: Decimal) -> str:
    definition = METRICS[rule.metric]
    return (
        f"{rule.name}: {definition.label.lower()} = {_format_value(value)} {definition.unit} "
        f"(umbral {OPERATOR_SYMBOLS[rule.operator]} {_format_value(rule.threshold)})"
    )


def _notify(alert: Alert, rule: AlertRule, now: datetime) -> None:
    if not rule.notify_emails:
        return
    settings = get_settings()
    if not settings.smtp_configured:
        alert.notification_error = "SMTP no configurado; alerta solo visible en la aplicación"
        return
    body = (
        f"Alerta {SEVERITY_LABELS[rule.severity].lower()} en AURORA LOGISTICS AI.\n\n"
        f"{alert.message}\n\n"
        f"Regla: {rule.name}\n"
        f"Severidad: {SEVERITY_LABELS[rule.severity]}\n"
        f"Detectada: {now.strftime('%d/%m/%Y %H:%M')} UTC\n\n"
        "Reconozca y resuelva la alerta en /alertas. Este mensaje es automático.\n"
    )
    message = Message(
        to=list(rule.notify_emails),
        subject=f"[AURORA][{SEVERITY_LABELS[rule.severity]}] {rule.name}",
        body=body,
    )
    try:
        send_mail(message)
        alert.notified_at = now
        alert.notification_error = ""
    except Exception as exc:  # noqa: BLE001 - la alerta debe persistir aunque falle el correo
        logger.warning("No se pudo notificar la alerta %s: %s", alert.id, exc)
        alert.notification_error = str(exc)[:500]


def evaluate_rules(
    db: Session, *, now: datetime | None = None
) -> dict[str, object]:
    """Evalúa todas las reglas activas. El llamador confirma la transacción."""
    moment = _as_utc(now or utcnow())
    active_rules = list(
        db.scalars(select(AlertRule).where(AlertRule.is_active.is_(True)).order_by(AlertRule.name)).all()
    )
    triggered: list[Alert] = []
    skipped = 0
    errors = 0

    for rule in active_rules:
        try:
            value = metric_value(db, rule.metric, moment)
            if not matches(value, rule.operator, rule.threshold):
                continue

            unresolved = db.scalar(
                select(Alert.id)
                .where(
                    Alert.rule_id == rule.id,
                    Alert.status.in_((AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)),
                )
                .limit(1)
            )
            if unresolved:
                skipped += 1
                continue

            if rule.cooldown_minutes > 0:
                since = moment - timedelta(minutes=rule.cooldown_minutes)
                recent = db.scalar(
                    select(Alert.id)
                    .where(Alert.rule_id == rule.id, Alert.triggered_at >= since)
                    .limit(1)
                )
                if recent:
                    skipped += 1
                    continue

            alert = Alert(
                rule_id=rule.id,
                status=AlertStatus.OPEN,
                severity=rule.severity,
                metric_value=value,
                threshold=rule.threshold,
                message=alert_message(rule, value),
                triggered_at=moment,
            )
            db.add(alert)
            db.flush()
            _notify(alert, rule, moment)
            record_audit(
                db,
                actor_user_id=None,
                actor_label="scheduler",
                action="alert.triggered",
                entity_type="alert",
                entity_id=alert.id,
                after={
                    "rule": rule.name,
                    "metric": rule.metric.value,
                    "value": str(value),
                    "threshold": str(rule.threshold),
                    "severity": rule.severity.value,
                    "notified": alert.notified_at is not None,
                },
            )
            triggered.append(alert)
        except Exception:  # noqa: BLE001 - una regla rota no bloquea al resto
            errors += 1
            logger.exception("Fallo al evaluar la regla de alerta %s", rule.name)

    db.flush()
    return {
        "evaluated": len(active_rules),
        "triggered": len(triggered),
        "skipped": skipped,
        "errors": errors,
        "alerts": triggered,
    }
