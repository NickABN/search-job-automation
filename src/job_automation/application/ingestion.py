"""Use cases and ports for source ingestion persistence."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from job_automation.domain.jobs import IngestionRun, NormalizedJobObservation


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
