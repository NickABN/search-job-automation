"""SQLAlchemy mappings for the ingestion persistence boundary."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SourceModel(Base):
    __tablename__ = "sources"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    identity: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class JobModel(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source_id", "source_job_id", name="uq_jobs_source_job"),
        Index("ix_jobs_source_id", "source_id"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_job_id: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    location_text: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observations: Mapped[list["JobObservationModel"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobObservationModel(Base):
    __tablename__ = "job_observations"
    __table_args__ = (
        UniqueConstraint("job_id", "content_hash", name="uq_observations_job_hash"),
        Index("ix_observations_job_observed_at", "job_id", "observed_at"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    job: Mapped[JobModel] = relationship(back_populates="observations")


class IngestionRunModel(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index("ix_ingestion_runs_source_started", "source_id", "started_at"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(String(1000))


class JobEvaluationModel(Base):
    __tablename__ = "job_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "profile_identifier",
            "policy_version",
            name="uq_job_evaluations_current",
        ),
        Index("ix_job_evaluations_eligible_score", "eligible", "score"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    factors: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    explanations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    exclusion_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class JobDigestModel(Base):
    __tablename__ = "job_digests"
    __table_args__ = (
        UniqueConstraint("local_date", "slot", name="uq_job_digests_key"),
        Index("ix_job_digests_selection", "local_date", "status"),
        CheckConstraint(
            "slot IN ('morning', 'midday', 'evening')", name="ck_job_digests_slot"
        ),
        CheckConstraint(
            "status IN ('empty', 'prepared', 'sending', 'sent', 'failed', 'uncertain')",
            name="ck_job_digests_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    local_date: Mapped[date] = mapped_column(Date(), nullable=False)
    slot: Mapped[str] = mapped_column(String(20), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobDigestItemModel(Base):
    __tablename__ = "job_digest_items"
    __table_args__ = (
        UniqueConstraint("digest_id", "job_id", name="uq_job_digest_job"),
        UniqueConstraint("digest_id", "item_index", name="uq_job_digest_index"),
        Index("ix_job_digest_items_job", "job_id"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_job_digest_item_score"),
        CheckConstraint("item_index >= 0", name="ck_job_digest_item_index"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    digest_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_digests.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    role_family: Mapped[str] = mapped_column(String(50), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class JobDigestDeliveryPartModel(Base):
    __tablename__ = "job_digest_delivery_parts"
    __table_args__ = (
        UniqueConstraint("digest_id", "part_index", name="uq_digest_delivery_part"),
        CheckConstraint("part_index >= 0", name="ck_delivery_part_index"),
        CheckConstraint("attempt_count >= 0", name="ck_delivery_attempt_count"),
        CheckConstraint(
            "state IN ('pending', 'sending', 'sent', 'permanent_failed', 'uncertain')",
            name="ck_delivery_part_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    digest_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_digests.id", ondelete="CASCADE"),
        nullable=False,
    )
    part_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(100))
    error_category: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class JobDigestDeliveryAttemptModel(Base):
    __tablename__ = "job_digest_delivery_attempts"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    part_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_digest_delivery_parts.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(100))
    provider_message_id: Mapped[str | None] = mapped_column(String(100))
