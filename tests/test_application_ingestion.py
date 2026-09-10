from datetime import UTC, datetime

import pytest

from job_automation.application.ingestion import (
    FetchedJob,
    IngestJobs,
    ObservationOutcome,
    SourceError,
)
from job_automation.domain.jobs import IngestionRunStatus, NormalizedJobObservation


def make_job() -> FetchedJob:
    return FetchedJob(
        NormalizedJobObservation(
            source="greenhouse",
            source_job_id="1",
            title="Engineer",
            company="Acme",
            description="Build",
            canonical_url="https://example.test/1",
            source_url=None,
            location_text=None,
            published_at=None,
            source_updated_at=None,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        {"id": 1},
    )


class Store:
    def __init__(self) -> None:
        self.runs = []
        self.outcomes = iter([ObservationOutcome.CREATED, ObservationOutcome.UNCHANGED])

    async def save(self, run: object) -> None:
        self.runs.append(run)

    async def record(
        self, observation: object, raw: dict[str, object]
    ) -> ObservationOutcome:
        return next(self.outcomes)


class Unit:
    def __init__(self, store: Store) -> None:
        self.runs = store
        self.observations = store

    async def __aenter__(self) -> "Unit":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_orchestration_records_counters_and_finishes() -> None:
    store = Store()
    clock_values = iter(
        [
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 3, tzinfo=UTC),
        ]
    )

    class Source:
        async def fetch(self, observed_at: datetime) -> list[FetchedJob]:
            return [make_job(), make_job()]

    result = await IngestJobs(
        Source(), lambda: Unit(store), lambda: next(clock_values), "greenhouse"
    ).execute()
    assert result.status is IngestionRunStatus.SUCCEEDED
    assert (result.fetched_count, result.created_count, result.unchanged_count) == (
        2,
        1,
        1,
    )
    assert store.runs[-1] == result


@pytest.mark.asyncio
async def test_source_failure_finishes_run_as_failed_with_safe_summary() -> None:
    store = Store()

    class Source:
        async def fetch(self, observed_at: datetime) -> list[FetchedJob]:
            raise SourceError("safe source failure")

    now = datetime(2026, 1, 1, tzinfo=UTC)
    result = await IngestJobs(
        Source(), lambda: Unit(store), lambda: now, "greenhouse"
    ).execute()
    assert result.status is IngestionRunStatus.FAILED
    assert result.error_summary == "safe source failure"


@pytest.mark.asyncio
async def test_recording_failure_preserves_committed_counters() -> None:
    class FailingStore(Store):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def record(
            self, observation: object, raw: dict[str, object]
        ) -> ObservationOutcome:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("database internals must not leak")
            return ObservationOutcome.CREATED

    store = FailingStore()

    class Source:
        async def fetch(self, observed_at: datetime) -> list[FetchedJob]:
            return [make_job(), make_job()]

    now = datetime(2026, 1, 1, tzinfo=UTC)
    result = await IngestJobs(
        Source(), lambda: Unit(store), lambda: now, "greenhouse:acme"
    ).execute()
    assert result.status is IngestionRunStatus.FAILED
    assert result.fetched_count == 2
    assert result.created_count == 1
    assert result.updated_count == 0
    assert result.unchanged_count == 0
    assert result.error_summary == "ingestion failed while recording observations"
