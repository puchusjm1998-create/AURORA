"""Phase 8: GPS tracking and delivery signature.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_tracking",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("accuracy_m", sa.Numeric(8, 2), nullable=True),
        sa.Column("speed_mps", sa.Numeric(6, 2), nullable=True),
        sa.Column("heading_deg", sa.Numeric(6, 2), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["delivery_id"], ["deliveries.id"],
            name="fk_delivery_tracking_delivery_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name="fk_delivery_tracking_created_by", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_delivery_tracking"),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90", name="ck_delivery_tracking_latitude"
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180", name="ck_delivery_tracking_longitude"
        ),
        sa.CheckConstraint(
            "accuracy_m IS NULL OR accuracy_m >= 0", name="ck_delivery_tracking_accuracy"
        ),
        sa.CheckConstraint(
            "speed_mps IS NULL OR speed_mps >= 0", name="ck_delivery_tracking_speed"
        ),
    )
    op.create_index("ix_delivery_tracking_delivery_id", "delivery_tracking", ["delivery_id"])
    op.create_index("ix_delivery_tracking_recorded_at", "delivery_tracking", ["recorded_at"])
    op.create_table(
        "delivery_signatures",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("signer_name", sa.String(length=120), nullable=False),
        sa.Column("signer_document", sa.String(length=32), nullable=False),
        sa.Column("signature_path", sa.String(length=255), nullable=False),
        sa.Column("signature_sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["delivery_id"], ["deliveries.id"],
            name="fk_delivery_signatures_delivery_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name="fk_delivery_signatures_created_by", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_delivery_signatures"),
        sa.UniqueConstraint("delivery_id", name="uq_delivery_signatures_delivery_id"),
    )
    op.create_index("ix_delivery_signatures_delivery_id", "delivery_signatures", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_signatures_delivery_id", table_name="delivery_signatures")
    op.drop_table("delivery_signatures")
    op.drop_index("ix_delivery_tracking_recorded_at", table_name="delivery_tracking")
    op.drop_index("ix_delivery_tracking_delivery_id", table_name="delivery_tracking")
    op.drop_table("delivery_tracking")
