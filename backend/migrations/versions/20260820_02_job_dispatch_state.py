"""add minimal task dispatch state

Revision ID: 20260820_02
Revises: 20260820_01
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260820_02"
down_revision = "20260820_01"
branch_labels = None
depends_on = None


def upgrade():
    # Existing Phase 1 rows were already dispatched by the old request path.
    op.add_column(
        "analysis_jobs",
        sa.Column(
            "dispatch_status",
            sa.String(24),
            nullable=False,
            server_default="DISPATCHED",
        ),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_analysis_jobs_dispatch_status", "analysis_jobs", ["dispatch_status"]
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("analysis_jobs") as batch_op:
            batch_op.alter_column("dispatch_status", server_default="PENDING")
    else:
        op.alter_column(
            "analysis_jobs",
            "dispatch_status",
            server_default="PENDING",
        )


def downgrade():
    op.drop_index("ix_analysis_jobs_dispatch_status", table_name="analysis_jobs")
    op.drop_column("analysis_jobs", "dispatched_at")
    op.drop_column("analysis_jobs", "dispatch_status")
