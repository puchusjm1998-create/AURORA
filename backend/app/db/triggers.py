"""Database-level guarantees.

* ``audit_logs`` is append-only: UPDATE and DELETE are rejected by triggers.
* ``stock_movements`` cannot be deleted, and the accounting fields of a
  confirmed movement are frozen at confirmation.
* ``delivery_tracking`` and ``delivery_signatures`` are append-only evidence:
  GPS points and signed delivery proofs cannot be altered or deleted.

These triggers run in both SQLite (dev/test) and PostgreSQL (production).
Each list entry below is exactly one statement.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

SQLITE_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_update
    BEFORE UPDATE ON audit_logs
    BEGIN
        SELECT RAISE(ABORT, 'audit_logs is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete
    BEFORE DELETE ON audit_logs
    BEGIN
        SELECT RAISE(ABORT, 'audit_logs is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS delivery_tracking_no_update
    BEFORE UPDATE ON delivery_tracking
    BEGIN
        SELECT RAISE(ABORT, 'delivery_tracking is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS delivery_tracking_no_delete
    BEFORE DELETE ON delivery_tracking
    BEGIN
        SELECT RAISE(ABORT, 'delivery_tracking is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS delivery_signatures_no_update
    BEFORE UPDATE ON delivery_signatures
    BEGIN
        SELECT RAISE(ABORT, 'delivery_signatures is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS delivery_signatures_no_delete
    BEFORE DELETE ON delivery_signatures
    BEGIN
        SELECT RAISE(ABORT, 'delivery_signatures is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS stock_movements_no_delete
    BEFORE DELETE ON stock_movements
    BEGIN
        SELECT RAISE(ABORT, 'stock_movements cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS stock_movements_confirmed_immutable
    BEFORE UPDATE ON stock_movements
    WHEN OLD.status = 'confirmed' AND (
        NEW.movement_type <> OLD.movement_type OR
        NEW.product_id <> OLD.product_id OR
        NEW.quantity <> OLD.quantity OR
        NEW.from_location_id IS NOT OLD.from_location_id OR
        NEW.to_location_id IS NOT OLD.to_location_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'confirmed stock movements are immutable');
    END
    """,
]

PG_TRIGGERS = [
    """
    CREATE OR REPLACE FUNCTION aurora_reject_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'Table % is append-only', TG_TABLE_NAME;
    END;
    $$ LANGUAGE plpgsql
    """,
    """DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs""",
    """
    CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION aurora_reject_mutation()
    """,
    """DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs""",
    """
    CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION aurora_reject_mutation()
    """,
    """DROP TRIGGER IF EXISTS delivery_tracking_no_update ON delivery_tracking""",
    """
    CREATE TRIGGER delivery_tracking_no_update BEFORE UPDATE ON delivery_tracking
    FOR EACH ROW EXECUTE FUNCTION aurora_reject_mutation()
    """,
    """DROP TRIGGER IF EXISTS delivery_tracking_no_delete ON delivery_tracking""",
    """
    CREATE TRIGGER delivery_tracking_no_delete BEFORE DELETE ON delivery_tracking
    FOR EACH ROW EXECUTE FUNCTION aurora_reject_mutation()
    """,
    """DROP TRIGGER IF EXISTS delivery_signatures_no_update ON delivery_signatures""",
    """
    CREATE TRIGGER delivery_signatures_no_update BEFORE UPDATE ON delivery_signatures
    FOR EACH ROW EXECUTE FUNCTION aurora_reject_mutation()
    """,
    """DROP TRIGGER IF EXISTS delivery_signatures_no_delete ON delivery_signatures""",
    """
    CREATE TRIGGER delivery_signatures_no_delete BEFORE DELETE ON delivery_signatures
    FOR EACH ROW EXECUTE FUNCTION aurora_reject_mutation()
    """,
    """DROP TRIGGER IF EXISTS stock_movements_no_delete ON stock_movements""",
    """
    CREATE TRIGGER stock_movements_no_delete BEFORE DELETE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION aurora_reject_mutation()
    """,
    """
    CREATE OR REPLACE FUNCTION aurora_guard_confirmed_movement() RETURNS trigger AS $$
    BEGIN
        IF OLD.status = 'confirmed' AND (
            NEW.movement_type <> OLD.movement_type OR
            NEW.product_id <> OLD.product_id OR
            NEW.quantity <> OLD.quantity OR
            NEW.from_location_id IS DISTINCT FROM OLD.from_location_id OR
            NEW.to_location_id IS DISTINCT FROM OLD.to_location_id
        ) THEN
            RAISE EXCEPTION 'confirmed stock movements are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """DROP TRIGGER IF EXISTS stock_movements_confirmed_immutable ON stock_movements""",
    """
    CREATE TRIGGER stock_movements_confirmed_immutable
    BEFORE UPDATE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION aurora_guard_confirmed_movement()
    """,
]


def install_immutability_triggers(engine: Engine) -> None:
    statements = SQLITE_TRIGGERS if engine.dialect.name == "sqlite" else PG_TRIGGERS
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
