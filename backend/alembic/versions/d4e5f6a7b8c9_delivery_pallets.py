"""Add pallets assigned to deliveries.

Revision ID: d4e5f6a7b8c9
Revises: 8c1f4b2a7d90
Create Date: 2026-11-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "8c1f4b2a7d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_pallets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("pallet_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["deliveries.id"],
            name="fk_delivery_pallets_delivery_id_deliveries",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pallet_id"],
            ["pallets.id"],
            name="fk_delivery_pallets_pallet_id_pallets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_delivery_pallets"),
        sa.UniqueConstraint("delivery_id", "pallet_id", name="uq_delivery_pallet"),
    )
    op.create_index("ix_delivery_pallets_delivery_id", "delivery_pallets", ["delivery_id"])
    op.create_index("ix_delivery_pallets_pallet_id", "delivery_pallets", ["pallet_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_pallets_pallet_id", table_name="delivery_pallets")
    op.drop_index("ix_delivery_pallets_delivery_id", table_name="delivery_pallets")
    op.drop_table("delivery_pallets")
