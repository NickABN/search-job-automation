import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from job_automation.application.digests import PrepareDigest
from job_automation.domain.digests import DigestSlot, DigestStatus
from job_automation.infrastructure.database import Database
from job_automation.infrastructure.digests import SqlAlchemyDigestUnitOfWork
from job_automation.infrastructure.models import (
    JobDigestItemModel,
    JobDigestModel,
    JobEvaluationModel,
    JobModel,
    SourceModel,
)

pytestmark = pytest.mark.integration
TZ = UTC
TODAY = date(2026, 9, 10)
SCHEDULED = datetime(2026, 9, 10, 15, tzinfo=UTC)


async def _reset(db: Database) -> None:
    async with db.session() as session:
        await session.execute(delete(JobDigestItemModel))
        await session.execute(delete(JobDigestModel))
        await session.execute(delete(JobEvaluationModel))
        await session.execute(delete(JobModel))
        await session.execute(delete(SourceModel))
        await session.commit()


async def _seed(db: Database, count: int = 3) -> list[str]:
    ids: list[str] = []
    async with db.session() as session:
        source = SourceModel(identity=f"digest-{uuid4()}", created_at=SCHEDULED)
        session.add(source)
        await session.flush()
        for index in range(count):
            job = JobModel(
                source_id=source.id,
                source_job_id=f"job-{index}",
                title=f"Engineer {index}",
                company=f"Company {index}",
                description="Build systems",
                canonical_url=f"https://example.test/{index}",
                source_url=None,
                location_text="Remote",
                first_seen_at=SCHEDULED,
                last_seen_at=SCHEDULED,
                current_content_hash=f"hash-{index}",
            )
            session.add(job)
            await session.flush()
            ids.append(str(job.id))
            session.add(
                JobEvaluationModel(
                    job_id=job.id,
                    profile_identifier="test",
                    policy_version="1",
                    eligible=True,
                    score=(90 - index * 10),
                    classification={"role_family": "backend"},
                    factors=[],
                    explanations=[f"reason {index}"],
                    exclusion_reasons=[],
                    evaluated_at=SCHEDULED,
                )
            )
        await session.commit()
    return ids


@pytest.fixture
async def database():
    from job_automation.config import get_settings

    db = Database(get_settings().database_url)
    await _reset(db)
    yield db
    await _reset(db)
    await db.dispose()


async def _prepare(db: Database, slot: DigestSlot, max_jobs: int = 20):
    return await PrepareDigest(
        lambda: SqlAlchemyDigestUnitOfWork(db.session_factory()), TZ, 60, max_jobs
    ).execute(TODAY, slot, SCHEDULED)


async def test_digest_selection_orders_threshold_and_max_jobs(
    database: Database,
) -> None:
    await _seed(database, 4)
    digest = await _prepare(database, DigestSlot.MORNING, 2)
    assert [item.score for item in digest.items] == [90, 80]


async def test_same_key_reuses_immutable_snapshot(database: Database) -> None:
    await _seed(database, 1)
    first = await _prepare(database, DigestSlot.MORNING)
    async with database.session() as session:
        job = await session.scalar(
            select(JobModel).where(JobModel.id == first.items[0].job_id)
        )
        assert job is not None
        job.title = "Changed live title"
        await session.commit()
    second = await _prepare(database, DigestSlot.MORNING)
    assert second.id == first.id
    assert second.items[0].title == first.items[0].title
    async with database.session() as session:
        assert (
            await session.scalar(select(func.count()).select_from(JobDigestItemModel))
            == 1
        )


async def test_empty_and_later_slot_exclusion(database: Database) -> None:
    await _seed(database, 1)
    morning = await _prepare(database, DigestSlot.MORNING)
    evening = await _prepare(database, DigestSlot.EVENING)
    assert morning.status is DigestStatus.PREPARED
    assert evening.status is DigestStatus.EMPTY


async def test_concurrent_slots_claim_one_job(database: Database) -> None:
    await _seed(database, 1)

    first, second = await asyncio.gather(
        _prepare(database, DigestSlot.MORNING),
        _prepare(database, DigestSlot.EVENING),
    )
    assert sorted((len(first.items), len(second.items))) == [0, 1]
