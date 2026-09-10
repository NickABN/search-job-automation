"""Digest preparation use case and persistence port."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from job_automation.domain.digests import DigestSlot, JobDigest


class DigestStore(Protocol):
    async def prepare(
        self,
        local_date: date,
        slot: DigestSlot,
        scheduled_at: datetime,
        threshold: int,
        max_jobs: int,
    ) -> JobDigest: ...


class DigestUnitOfWork(Protocol):
    digests: DigestStore

    async def __aenter__(self) -> "DigestUnitOfWork": ...
    async def __aexit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PrepareDigest:
    unit_of_work_factory: Callable[[], DigestUnitOfWork]
    timezone: ZoneInfo
    threshold: int = 60
    max_jobs: int = 20

    async def execute(
        self, local_date: date, slot: DigestSlot, scheduled_at: datetime
    ) -> JobDigest:
        if not 0 <= self.threshold <= 100:
            raise ValueError("threshold must be between 0 and 100")
        if not 1 <= self.max_jobs <= 1000:
            raise ValueError("max_jobs must be between 1 and 1000")
        if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if scheduled_at.astimezone(self.timezone).date() != local_date:
            raise ValueError("scheduled_at must belong to local_date")
        async with self.unit_of_work_factory() as work:
            return await work.digests.prepare(
                local_date, slot, scheduled_at, self.threshold, self.max_jobs
            )
