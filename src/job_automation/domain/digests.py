"""Immutable domain objects for scheduled job digests."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class DigestSlot(StrEnum):
    MORNING = "morning"
    MIDDAY = "midday"
    EVENING = "evening"


class DigestStatus(StrEnum):
    EMPTY = "empty"
    PREPARED = "prepared"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class DigestItem:
    job_id: str
    title: str
    company: str
    location: str
    canonical_url: str
    score: int
    role_family: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "job_id",
            "title",
            "company",
            "location",
            "canonical_url",
            "role_family",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")
        if not self.reasons or any(not reason.strip() for reason in self.reasons):
            raise ValueError("reasons must contain nonblank values")


@dataclass(frozen=True, slots=True)
class JobDigest:
    id: str
    local_date: date
    slot: DigestSlot
    scheduled_at: datetime
    status: DigestStatus
    items: tuple[DigestItem, ...]
    sent_at: datetime | None = None

    @property
    def idempotency_key(self) -> str:
        return f"{self.local_date.isoformat()}:{self.slot.value}"

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if self.sent_at is not None and (
            self.sent_at.tzinfo is None or self.sent_at.utcoffset() is None
        ):
            raise ValueError("sent_at must be timezone-aware")
        ids = [item.job_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("digest items must contain unique jobs")
        if self.status is DigestStatus.EMPTY and self.items:
            raise ValueError("empty digest cannot contain items")
        if self.status is not DigestStatus.EMPTY and not self.items:
            raise ValueError("non-empty digest must contain items")

    def transition(self, status: DigestStatus) -> "JobDigest":
        allowed = {
            DigestStatus.PREPARED: {DigestStatus.SENDING},
            DigestStatus.SENDING: {
                DigestStatus.SENT,
                DigestStatus.FAILED,
                DigestStatus.UNCERTAIN,
            },
            DigestStatus.SENT: set(),
            DigestStatus.FAILED: set(),
            DigestStatus.UNCERTAIN: set(),
            DigestStatus.EMPTY: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"invalid digest transition {self.status} -> {status}")
        return JobDigest(
            self.id,
            self.local_date,
            self.slot,
            self.scheduled_at,
            status,
            self.items,
            self.sent_at if status is not DigestStatus.SENT else self.sent_at,
        )
