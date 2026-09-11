"""Allow the midday scheduled digest slot."""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_midday_digest_slot"
down_revision: str | None = "0004_telegram_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_job_digests_slot", "job_digests", type_="check")
    op.create_check_constraint(
        "ck_job_digests_slot",
        "job_digests",
        "slot IN ('morning', 'midday', 'evening')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_digests_slot", "job_digests", type_="check")
    op.create_check_constraint(
        "ck_job_digests_slot",
        "job_digests",
        "slot IN ('morning', 'evening')",
    )
