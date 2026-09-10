"""Add idempotent immutable job digests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_job_digests"
down_revision: str | None = "0002_job_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_digests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("local_date", "slot", name="uq_job_digests_key"),
        sa.CheckConstraint(
            "slot IN ('morning', 'evening')", name="ck_job_digests_slot"
        ),
        sa.CheckConstraint(
            "status IN ('empty', 'prepared', 'sending', 'sent')",
            name="ck_job_digests_status",
        ),
    )
    op.create_index("ix_job_digests_selection", "job_digests", ["local_date", "status"])
    op.create_table(
        "job_digest_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "digest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_digests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("company", sa.String(300), nullable=False),
        sa.Column("location", sa.String(500), nullable=False),
        sa.Column("canonical_url", sa.String(2000), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("role_family", sa.String(50), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("digest_id", "job_id", name="uq_job_digest_job"),
        sa.UniqueConstraint("digest_id", "item_index", name="uq_job_digest_index"),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name="ck_job_digest_item_score"
        ),
        sa.CheckConstraint("item_index >= 0", name="ck_job_digest_item_index"),
    )
    op.create_index("ix_job_digest_items_job", "job_digest_items", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_digest_items_job", table_name="job_digest_items")
    op.drop_table("job_digest_items")
    op.drop_index("ix_job_digests_selection", table_name="job_digests")
    op.drop_table("job_digests")
