"""Reservation housekeeping.

Reservations can carry an expiry date. The rule is enforced by the server, not
just displayed: any active reservation past ``expires_at`` is released and its
units return to ``available`` before stock is read or consumed.

The sweep is idempotent and commits its own transaction, so any read endpoint
can call it safely. Each expiry is written to the immutable audit log with no
human actor (``Sistema``) so the release can always be explained.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.audit import record_audit
from app.services.stock import StockEngine


def expire_due(db: Session) -> int:
    expired = StockEngine(db).expire_due_reservations()
    for reservation in expired:
        record_audit(
            db,
            actor_user_id=None,
            actor_label="Sistema (caducidad de reserva)",
            action="reservation.expired",
            entity_type="stock_reservation",
            entity_id=reservation.id,
            before={"status": "active"},
            after={
                "status": "expired",
                "reference": reservation.reference,
                "quantity": str(reservation.quantity),
                "expires_at": reservation.expires_at.isoformat() if reservation.expires_at else None,
            },
        )
    if expired:
        db.commit()
    return len(expired)
