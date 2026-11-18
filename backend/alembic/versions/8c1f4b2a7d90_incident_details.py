"""Add incident type, product and pallet links.

Revision ID: 8c1f4b2a7d90
Revises: e0ec52100839
Create Date: 2026-11-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8c1f4b2a7d90"
down_revision = "e0ec52100839"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "incident_type",
                sa.Enum(
                    "DAMAGE",
                    "DISCREPANCY",
                    "QUALITY",
                    "SAFETY",
                    "OTHER",
                    name="incident_type",
                    native_enum=False,
                    length=32,
                ),
                server_default="OTHER",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("product_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("pallet_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_incidents_product_id", ["product_id"], unique=False)
        batch_op.create_index("ix_incidents_pallet_id", ["pallet_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_incidents_product_id_products",
            "products",
            ["product_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_incidents_pallet_id_pallets",
            "pallets",
            ["pallet_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.drop_constraint("fk_incidents_pallet_id_pallets", type_="foreignkey")
        batch_op.drop_constraint("fk_incidents_product_id_products", type_="foreignkey")
        batch_op.drop_index("ix_incidents_pallet_id")
        batch_op.drop_index("ix_incidents_product_id")
        batch_op.drop_column("pallet_id")
        batch_op.drop_column("product_id")
        batch_op.drop_column("incident_type")
