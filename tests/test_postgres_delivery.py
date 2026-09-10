import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from job_automation.application.notifications import DeliveryPart, DeliveryState
from job_automation.domain.digests import (
    DigestItem,
    DigestSlot,
    DigestStatus,
    JobDigest,
)
from job_automation.infrastructure.database import Database
from job_automation.infrastructure.delivery import SqlAlchemyDeliveryStore
from job_automation.infrastructure.models import (
    JobDigestDeliveryAttemptModel,
    JobDigestDeliveryPartModel,
    JobDigestModel,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 10, 15, tzinfo=UTC)


@pytest.fixture
async def database():
    from job_automation.config import get_settings

    db = Database(get_settings().database_url)
    async with db.session() as session:
        await session.execute(delete(JobDigestDeliveryAttemptModel))
        await session.execute(delete(JobDigestDeliveryPartModel))
        await session.execute(delete(JobDigestModel))
        await session.commit()
    yield db
    async with db.session() as session:
        await session.execute(delete(JobDigestDeliveryAttemptModel))
        await session.execute(delete(JobDigestDeliveryPartModel))
        await session.execute(delete(JobDigestModel))
        await session.commit()
    await db.dispose()


def digest(identifier: str | None = None) -> JobDigest:
    return JobDigest(
        identifier or str(uuid4()),
        date(2026, 9, 10),
        DigestSlot.MORNING,
        NOW,
        DigestStatus.PREPARED,
        (
            DigestItem(
                "job-1",
                "Engineer",
                "Acme",
                "Remote",
                "https://example.test/job",
                80,
                "backend",
                ("reason",),
            ),
        ),
    )


async def create_digest(database: Database) -> JobDigest:
    value = digest()
    async with database.session() as session:
        session.add(
            JobDigestModel(
                id=value.id,
                local_date=value.local_date,
                slot=value.slot.value,
                scheduled_at=value.scheduled_at,
                status=value.status.value,
            )
        )
        await session.commit()
    return value


async def test_attempt_is_persisted_and_reconciled(database: Database) -> None:
    value = await create_digest(database)
    async with database.session() as session:
        store = SqlAlchemyDeliveryStore(session)
        await store.prepare_parts(value, ("part",))
        await session.commit()
    async with database.session() as session:
        store = SqlAlchemyDeliveryStore(session)
        part = (await store.prepare_parts(value, ("part",)))[0]
        claimed = await store.claim_sending(part, NOW)
        assert claimed is not None
        await store.mark_sent(claimed, "42", NOW)
        await session.commit()
    async with database.session() as session:
        row = await session.scalar(select(JobDigestDeliveryPartModel))
        attempt = await session.scalar(select(JobDigestDeliveryAttemptModel))
        assert row is not None and row.state == "sent"
        assert attempt is not None and attempt.state == "sent"
        assert attempt.provider_message_id == "42"
        assert attempt.completed_at == NOW


async def test_concurrent_claims_only_one_sender_wins(database: Database) -> None:
    value = await create_digest(database)
    async with database.session() as session:
        store = SqlAlchemyDeliveryStore(session)
        await store.prepare_parts(value, ("part",))
        await session.commit()

    async def claim() -> DeliveryPart | None:
        async with database.session() as session:
            store = SqlAlchemyDeliveryStore(session)
            part = (await store.prepare_parts(value, ("part",)))[0]
            result = await store.claim_sending(part, NOW)
            await session.commit()
            return result

    first, second = await asyncio.gather(claim(), claim())
    assert sorted((first is not None, second is not None)) == [False, True]


async def test_sending_is_not_automatically_reclaimed(database: Database) -> None:
    value = await create_digest(database)
    async with database.session() as session:
        store = SqlAlchemyDeliveryStore(session)
        part = (await store.prepare_parts(value, ("part",)))[0]
        claimed = await store.claim_sending(part, NOW)
        assert claimed is not None
        await session.commit()
    async with database.session() as session:
        store = SqlAlchemyDeliveryStore(session)
        persisted = (await store.prepare_parts(value, ("part",)))[0]
        assert persisted.state is DeliveryState.SENDING
        assert await store.claim_sending(persisted, NOW) is None
