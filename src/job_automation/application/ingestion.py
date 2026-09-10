"""Use cases and ports for source ingestion persistence."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from job_automation.domain.jobs import IngestionRun, NormalizedJobObservation


@dataclass(frozen=True, slots=True)
class FetchedJob:
    """A source-neutral normalized observation and its source payload."""

    observation: NormalizedJobObservation
    raw_payload: dict[str, object]


class JobSource(Protocol):
    async def fetch(self, observed_at: datetime) -> Sequence[FetchedJob]: ...


class ObservationOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


class ObservationStore(Protocol):
    async def record(
        self, observation: NormalizedJobObservation, raw_payload: dict[str, object]
    ) -> ObservationOutcome: ...


class IngestionRunStore(Protocol):
    async def save(self, run: IngestionRun) -> None: ...


class IngestionUnitOfWork(Protocol):
    observations: ObservationStore
    runs: IngestionRunStore

    async def __aenter__(self) -> "IngestionUnitOfWork": ...
    async def __aexit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> None: ...


@dataclass(frozen=True)
class RecordJobObservation:
    unit_of_work_factory: Callable[[], IngestionUnitOfWork]

    async def execute(
        self, observation: NormalizedJobObservation, raw_payload: dict[str, object]
    ) -> ObservationOutcome:
        async with self.unit_of_work_factory() as unit_of_work:
            return await unit_of_work.observations.record(observation, raw_payload)


@dataclass(frozen=True)
class StartIngestionRun:
    unit_of_work_factory: Callable[[], IngestionUnitOfWork]

    async def execute(self, run: IngestionRun) -> None:
        async with self.unit_of_work_factory() as unit_of_work:
            await unit_of_work.runs.save(run)


@dataclass(frozen=True)
class FinishIngestionRun:
    unit_of_work_factory: Callable[[], IngestionUnitOfWork]

    async def execute(
        self,
        run: IngestionRun,
        *,
        finished_at: datetime,
        fetched: int,
        created: int,
        updated: int,
        unchanged: int,
    ) -> IngestionRun:
        finished = run.finish(
            finished_at,
            fetched=fetched,
            created=created,
            updated=updated,
            unchanged=unchanged,
        )
        async with self.unit_of_work_factory() as unit_of_work:
            await unit_of_work.runs.save(finished)
        return finished


@dataclass(frozen=True)
class FailIngestionRun:
    unit_of_work_factory: Callable[[], IngestionUnitOfWork]

    async def execute(
        self, run: IngestionRun, *, finished_at: datetime, error_summary: str
    ) -> IngestionRun:
        failed = run.fail(finished_at, error_summary)
        async with self.unit_of_work_factory() as unit_of_work:
            await unit_of_work.runs.save(failed)
        return failed


@dataclass(frozen=True)
class IngestJobs:
    source: JobSource
    unit_of_work_factory: Callable[[], IngestionUnitOfWork]
    clock: Callable[[], datetime]
    source_name: str

    async def execute(self) -> IngestionRun:
        started_at = self.clock()
        run = IngestionRun.start(self.source_name, started_at)
        async with self.unit_of_work_factory() as unit_of_work:
            await unit_of_work.runs.save(run)

        try:
            fetched_jobs = await self.source.fetch(self.clock())
        except Exception as exc:  # source failures are represented by a failed run
            failed = run.fail(self.clock(), _safe_error_summary(exc))
            async with self.unit_of_work_factory() as unit_of_work:
                await unit_of_work.runs.save(failed)
            return failed

        counts = {outcome: 0 for outcome in ObservationOutcome}
        try:
            for fetched_job in fetched_jobs:
                async with self.unit_of_work_factory() as unit_of_work:
                    outcome = await unit_of_work.observations.record(
                        fetched_job.observation, fetched_job.raw_payload
                    )
                counts[outcome] += 1
        except Exception:
            failed = run.fail(
                self.clock(),
                "ingestion failed while recording observations",
                fetched=len(fetched_jobs),
                created=counts[ObservationOutcome.CREATED],
                updated=counts[ObservationOutcome.UPDATED],
                unchanged=counts[ObservationOutcome.UNCHANGED],
            )
            async with self.unit_of_work_factory() as unit_of_work:
                await unit_of_work.runs.save(failed)
            return failed

        finished = run.finish(
            self.clock(),
            fetched=len(fetched_jobs),
            created=counts[ObservationOutcome.CREATED],
            updated=counts[ObservationOutcome.UPDATED],
            unchanged=counts[ObservationOutcome.UNCHANGED],
        )
        async with self.unit_of_work_factory() as unit_of_work:
            await unit_of_work.runs.save(finished)
        return finished


def _safe_error_summary(error: Exception) -> str:
    if isinstance(error, SourceError):
        return str(error)
    return "ingestion failed while processing the configured source"


class SourceError(Exception):
    """Stable, safe-to-persist source failure."""
