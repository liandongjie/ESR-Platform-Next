"""add job idempotency and lifecycle metadata

Revision ID: 20260820_03
Revises: 20260820_02
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260820_03"
down_revision = "20260820_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("analysis_jobs", sa.Column("idempotency_key", sa.String(128)))
    op.add_column("analysis_jobs", sa.Column("parent_job_id", sa.String(36)))
    op.add_column("analysis_jobs", sa.Column("expires_at", sa.DateTime(timezone=True)))
    # Revisions 01-03 ship in one multi-user release, so production has no
    # pre-existing database jobs. This fallback only keeps local/partial upgrades valid;
    # legacy file-only runtime jobs are intentionally not backfilled.
    op.execute(
        sa.text(
            "UPDATE analysis_jobs "
            "SET idempotency_key = 'legacy:' || id "
            "WHERE idempotency_key IS NULL"
        )
    )

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("analysis_jobs") as batch_op:
            batch_op.alter_column("idempotency_key", nullable=False)
            batch_op.create_foreign_key(
                "fk_analysis_jobs_parent_job_id",
                "analysis_jobs",
                ["parent_job_id"],
                ["id"],
            )
            batch_op.create_unique_constraint(
                "uq_analysis_jobs_owner_id_idempotency_key",
                ["owner_id", "idempotency_key"],
            )
    else:
        op.alter_column("analysis_jobs", "idempotency_key", nullable=False)
        op.create_foreign_key(
            "fk_analysis_jobs_parent_job_id",
            "analysis_jobs",
            "analysis_jobs",
            ["parent_job_id"],
            ["id"],
        )
        op.create_unique_constraint(
            "uq_analysis_jobs_owner_id_idempotency_key",
            "analysis_jobs",
            ["owner_id", "idempotency_key"],
        )

    op.create_index("ix_analysis_jobs_parent_job_id", "analysis_jobs", ["parent_job_id"])
    op.create_index("ix_analysis_jobs_expires_at", "analysis_jobs", ["expires_at"])
    op.add_column(
        "analysis_artifacts", sa.Column("expires_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "analysis_artifacts", sa.Column("deleted_at", sa.DateTime(timezone=True))
    )


def downgrade():
    op.drop_column("analysis_artifacts", "deleted_at")
    op.drop_column("analysis_artifacts", "expires_at")
    op.drop_index("ix_analysis_jobs_expires_at", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_parent_job_id", table_name="analysis_jobs")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("analysis_jobs") as batch_op:
            batch_op.drop_constraint(
                "uq_analysis_jobs_owner_id_idempotency_key", type_="unique"
            )
            batch_op.drop_constraint(
                "fk_analysis_jobs_parent_job_id", type_="foreignkey"
            )
            batch_op.drop_column("expires_at")
            batch_op.drop_column("parent_job_id")
            batch_op.drop_column("idempotency_key")
    else:
        op.drop_constraint(
            "uq_analysis_jobs_owner_id_idempotency_key",
            "analysis_jobs",
            type_="unique",
        )
        op.drop_constraint(
            "fk_analysis_jobs_parent_job_id", "analysis_jobs", type_="foreignkey"
        )
        op.drop_column("analysis_jobs", "expires_at")
        op.drop_column("analysis_jobs", "parent_job_id")
        op.drop_column("analysis_jobs", "idempotency_key")
