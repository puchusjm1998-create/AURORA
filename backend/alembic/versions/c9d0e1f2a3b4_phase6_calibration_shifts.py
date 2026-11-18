"""Phase 6: warehouse calibration, field time samples and work shifts.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouse_calibrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("aisle_pitch_m", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("rack_pitch_m", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("position_pitch_m", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("base_pick_seconds", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("level_penalty_seconds", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("walking_speed_mps", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("setup_seconds", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("r_squared", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("mae_seconds", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calibrated_by", sa.String(length=36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["warehouses.id"],
            name="fk_warehouse_calibrations_warehouse_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["calibrated_by"], ["users.id"],
            name="fk_warehouse_calibrations_calibrated_by", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warehouse_calibrations"),
        sa.UniqueConstraint("warehouse_id", name="uq_warehouse_calibrations_warehouse_id"),
        sa.CheckConstraint("walking_speed_mps > 0", name="ck_calibration_speed_positive"),
        sa.CheckConstraint("base_pick_seconds >= 0", name="ck_calibration_pick_non_negative"),
    )
    op.create_table(
        "route_time_samples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("location_ids", sa.JSON(), nullable=False),
        sa.Column("stops", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("measured_seconds", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measured_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["warehouses.id"],
            name="fk_route_time_samples_warehouse_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["measured_by"], ["users.id"],
            name="fk_route_time_samples_measured_by", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_route_time_samples"),
        sa.CheckConstraint("measured_seconds > 0", name="ck_time_sample_positive"),
    )
    op.create_index("ix_route_time_samples_warehouse_id", "route_time_samples", ["warehouse_id"])
    op.create_table(
        "work_shifts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("days_of_week", sa.JSON(), nullable=False),
        sa.Column("required_headcount", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["warehouses.id"],
            name="fk_work_shifts_warehouse_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name="fk_work_shifts_created_by", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_shifts"),
        sa.CheckConstraint("required_headcount >= 1", name="ck_work_shifts_headcount"),
    )
    op.create_index("ix_work_shifts_warehouse_id", "work_shifts", ["warehouse_id"])
    op.create_table(
        "shift_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("shift_id", sa.String(length=36), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["shift_id"], ["work_shifts.id"],
            name="fk_shift_assignments_shift_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"],
            name="fk_shift_assignments_employee_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name="fk_shift_assignments_created_by", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shift_assignments"),
        sa.UniqueConstraint(
            "shift_id", "employee_id", "work_date", name="uq_shift_employee_date"
        ),
    )
    op.create_index("ix_shift_assignments_shift_id", "shift_assignments", ["shift_id"])
    op.create_index("ix_shift_assignments_employee_id", "shift_assignments", ["employee_id"])
    op.create_index("ix_shift_assignments_work_date", "shift_assignments", ["work_date"])


def downgrade() -> None:
    op.drop_index("ix_shift_assignments_work_date", table_name="shift_assignments")
    op.drop_index("ix_shift_assignments_employee_id", table_name="shift_assignments")
    op.drop_index("ix_shift_assignments_shift_id", table_name="shift_assignments")
    op.drop_table("shift_assignments")
    op.drop_index("ix_work_shifts_warehouse_id", table_name="work_shifts")
    op.drop_table("work_shifts")
    op.drop_index("ix_route_time_samples_warehouse_id", table_name="route_time_samples")
    op.drop_table("route_time_samples")
    op.drop_table("warehouse_calibrations")
