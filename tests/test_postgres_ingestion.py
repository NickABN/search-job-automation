from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from job_automation.domain.jobs import IngestionRun, NormalizedJobObservation
from job_automation.infrastructure.ingestion import SqlAlchemyIngestionUnitOfWork
from job_automation.infrastructure.models import (
    IngestionRunModel,
    JobModel,
    JobObservationModel,
)

pytestmark = pytest.mark.integration


def make_observation(
    description: str, observed_at: datetime | None = None
) -> NormalizedJobObservation:
    return NormalizedJobObservation(
        source="integration",
        source_job_id="job-1",
        title="Engineer",
        company="Acme",
        description=description,
        canonical_url="https://example.test/job-1",
        source_url=None,
        location_text="Remote",
        published_at=None,
        source_updated_at=None,
        observed_at=observed_at or datetime.now(UTC),
    )


@pytest.fixture
async def session(database: object):
    async with database.session() as db_session:  # type: ignore[attr-defined]
        await db_session.execute(JobObservationModel.__table__.delete())
        await db_session.execute(JobModel.__table__.delete())
        await db_session.commit()
        yield db_session


@pytest.fixture
async def database():
    from job_automation.config import get_settings
    from job_automation.infrastructure.database import Database

    db = Database(get_settings().database_url)
    yield db
    await db.dispose()


async def test_repeated_and_changed_observations_are_idempotent(
    session: object,
) -> None:
    def unit() -> SqlAlchemyIngestionUnitOfWork:
        return SqlAlchemyIngestionUnitOfWork(session)  # type: ignore[arg-type]

    first = make_observation("Build things")
    async with unit() as work:
        assert await work.observations.record(first, {"title": "Engineer"}) == "created"
    async with unit() as work:
        assert (
            await work.observations.record(first, {"title": "Engineer"}) == "unchanged"
        )
    changed = make_observation("Build better things")
    async with unit() as work:
        assert (
            await work.observations.record(changed, {"title": "Engineer", "v": 2})
            == "updated"
        )
    count = await session.scalar(select(func.count()).select_from(JobObservationModel))  # type: ignore[attr-defined]
    assert count == 2


async def test_returning_to_historical_state_updates_projection_without_duplicate(
    session: object,
) -> None:
    def unit() -> SqlAlchemyIngestionUnitOfWork:
        return SqlAlchemyIngestionUnitOfWork(session)  # type: ignore[arg-type]

    first = make_observation("State A", datetime(2026, 1, 1, tzinfo=UTC))
    second = make_observation("State B", datetime(2026, 1, 2, tzinfo=UTC))
    older_return = make_observation("State A", datetime(2025, 12, 1, tzinfo=UTC))
    async with unit() as work:
        assert await work.observations.record(first, {"state": "a"}) == "created"
    async with unit() as work:
        assert await work.observations.record(second, {"state": "b"}) == "updated"
    async with unit() as work:
        assert (
            await work.observations.record(older_return, {"state": "a-again"})
            == "updated"
        )

    job = await session.scalar(  # type: ignore[attr-defined]
        select(JobModel).where(JobModel.source_job_id == "job-1")
    )
    count = await session.scalar(
        select(func.count()).select_from(JobObservationModel)  # type: ignore[attr-defined]
    )
    assert job is not None
    assert job.description == "State A"
    assert job.current_content_hash == first.content_hash
    assert job.last_seen_at == second.observed_at
    assert count == 2


async def test_transaction_rolls_back_partial_observation(session: object) -> None:
    def unit() -> SqlAlchemyIngestionUnitOfWork:
        return SqlAlchemyIngestionUnitOfWork(session)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="abort"):
        async with unit() as work:
            await work.observations.record(make_observation("never commit"), {})
            raise RuntimeError("abort")
    count = await session.scalar(select(func.count()).select_from(JobModel))  # type: ignore[attr-defined]
    assert count == 0


async def test_ingestion_run_store_persists_transition(session: object) -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    run = IngestionRun.start("integration-runs", started_at)
    finished = run.finish(
        datetime(2026, 1, 2, tzinfo=UTC),
        fetched=3,
        created=1,
        updated=1,
        unchanged=1,
    )
    async with SqlAlchemyIngestionUnitOfWork(session) as work:  # type: ignore[arg-type]
        await work.runs.save(run)
    async with SqlAlchemyIngestionUnitOfWork(session) as work:  # type: ignore[arg-type]
        await work.runs.save(finished)
    model = await session.scalar(  # type: ignore[attr-defined]
        select(IngestionRunModel).where(IngestionRunModel.source_id.is_not(None))
    )
    assert model is not None
    assert model.status == "succeeded"
    assert model.fetched_count == 3
