"""Add current explainable job evaluations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_job_evaluations"
down_revision: str | None = "0001_initial_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_identifier", sa.String(200), nullable=False),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("classification", postgresql.JSONB(), nullable=False),
        sa.Column("factors", postgresql.JSONB(), nullable=False),
        sa.Column("explanations", postgresql.JSONB(), nullable=False),
        sa.Column("exclusion_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "job_id",
            "profile_identifier",
            "policy_version",
            name="uq_job_evaluations_current",
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name="ck_job_evaluations_score"
        ),
    )
    op.create_index(
        "ix_job_evaluations_eligible_score", "job_evaluations", ["eligible", "score"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_evaluations_eligible_score", table_name="job_evaluations")
    op.drop_table("job_evaluations")
