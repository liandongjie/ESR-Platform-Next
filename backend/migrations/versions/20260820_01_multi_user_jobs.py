"""add users and owned analysis jobs

Revision ID: 20260820_01
Revises:
Create Date: 2026-08-20
"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision = "20260820_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    geometry_type = (
        geoalchemy2.Geometry("GEOMETRY", srid=4326)
        if bind.dialect.name == "postgresql"
        else sa.JSON()
    )
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("geometry", geometry_type, nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_analysis_jobs_owner_id", "analysis_jobs", ["owner_id"])
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])
    op.create_index("ix_analysis_jobs_queued_at", "analysis_jobs", ["queued_at"])
    op.create_table(
        "analysis_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("job_id", "kind"),
    )
    op.create_index("ix_analysis_artifacts_job_id", "analysis_artifacts", ["job_id"])


def downgrade():
    op.drop_index("ix_analysis_artifacts_job_id", table_name="analysis_artifacts")
    op.drop_table("analysis_artifacts")
    op.drop_index("ix_analysis_jobs_queued_at", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_owner_id", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
