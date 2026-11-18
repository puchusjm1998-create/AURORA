"""Phase 7: NFC cards and hours bank.

Revision ID: e1f2a3b4c5d6
Revises: c9d0e1f2a3b4
Create Date: 2026-11-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.add_column(
            sa.Column(
                "weekly_hours", sa.Numeric(5, 2), nullable=False, server_default="40"
            )
        )
    op.create_table(
        "nfc_cards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_last4", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"],
            name="fk_nfc_cards_employee_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"], ["users.id"], name="fk_nfc_cards_revoked_by", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_nfc_cards_created_by", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_nfc_cards"),
        sa.UniqueConstraint("token_hash", name="uq_nfc_cards_token_hash"),
    )
    op.create_index("ix_nfc_cards_employee_id", "nfc_cards", ["employee_id"])
    op.create_table(
        "hours_bank_adjustments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"],
            name="fk_hours_bank_adjustments_employee_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name="fk_hours_bank_adjustments_created_by", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hours_bank_adjustments"),
        sa.CheckConstraint("minutes <> 0", name="ck_hours_adjustment_non_zero"),
        sa.CheckConstraint(
            "minutes BETWEEN -100000 AND 100000", name="ck_hours_adjustment_range"
        ),
    )
    op.create_index(
        "ix_hours_bank_adjustments_employee_id", "hours_bank_adjustments", ["employee_id"]
    )
    op.create_index(
        "ix_hours_bank_adjustments_effective_date", "hours_bank_adjustments", ["effective_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_hours_bank_adjustments_effective_date", table_name="hours_bank_adjustments")
    op.drop_index("ix_hours_bank_adjustments_employee_id", table_name="hours_bank_adjustments")
    op.drop_table("hours_bank_adjustments")
    op.drop_index("ix_nfc_cards_employee_id", table_name="nfc_cards")
    op.drop_table("nfc_cards")
    with op.batch_alter_table("employees") as batch:
        batch.drop_column("weekly_hours")
