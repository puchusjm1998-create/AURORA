"""Append-only audit trail.

Every mutating operation writes an ``AuditLog`` row inside the same database
transaction as the change it describes, so a change never exists without its
audit entry. The table is protected against UPDATE/DELETE by database triggers
(see ``app/db/triggers.py``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def record_audit(
    db: Session,
    *,
    actor_user_id: str | None,
    actor_label: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_label=actor_label or "system",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=jsonable(before) if before is not None else None,
        after=jsonable(after) if after is not None else None,
        ip=ip,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(entry)
    return entry
