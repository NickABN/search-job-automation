"""Add resumable digest delivery parts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_telegram_delivery"
down_revision: str | None = "0003_job_digests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_job_digests_status", "job_digests", type_="check")
    op.create_check_constraint(
        "ck_job_digests_status",
        "job_digests",
        "status IN ('empty', 'prepared', 'sending', 'sent', 'failed', 'uncertain')",
    )
    op.add_column(
        "job_digests", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "job_digest_delivery_parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "digest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_digests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_message_id", sa.String(100), nullable=True),
        sa.Column("error_category", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("digest_id", "part_index", name="uq_digest_delivery_part"),
        sa.CheckConstraint(
            "state IN ('pending', 'sending', 'sent', 'permanent_failed', 'uncertain')",
            name="ck_delivery_part_state",
        ),
        sa.CheckConstraint("part_index >= 0", name="ck_delivery_part_index"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_delivery_attempt_count"),
    )
    op.create_table(
        "job_digest_delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "part_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_digest_delivery_parts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("error_category", sa.String(100), nullable=True),
        sa.Column("provider_message_id", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("job_digest_delivery_attempts")
    op.drop_table("job_digest_delivery_parts")
    op.drop_column("job_digests", "sent_at")
    op.drop_constraint("ck_job_digests_status", "job_digests", type_="check")
    op.create_check_constraint(
        "ck_job_digests_status",
        "job_digests",
        "status IN ('empty', 'prepared', 'sending', 'sent')",
    )
