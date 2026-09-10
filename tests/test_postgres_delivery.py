import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from job_automation.application.notifications import (
    DeliverDigest,
    DeliveryPart,
    DeliveryState,
)
from job_automation.domain.digests import (
    DigestItem,
    DigestSlot,
    DigestStatus,
    JobDigest,
)
from job_automation.infrastructure.database import Database
from job_automation.infrastructure.delivery import (
    SqlAlchemyDeliveryStore,
    SqlAlchemyDeliveryUnitOfWork,
)
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


async def test_gateway_observes_committed_claim_before_dispatch(
    database: Database,
) -> None:
    value = await create_digest(database)
    observed: list[tuple[str, str, str]] = []

    class Gateway:
        async def send(self, content: str) -> str:
            async with database.session() as session:
                digest_row = await session.scalar(select(JobDigestModel))
                part_row = await session.scalar(select(JobDigestDeliveryPartModel))
                attempt_row = await session.scalar(
                    select(JobDigestDeliveryAttemptModel)
                )
                assert digest_row is not None
                assert part_row is not None
                assert attempt_row is not None
                observed.append((digest_row.status, part_row.state, attempt_row.state))
            return "42"

    async with SqlAlchemyDeliveryUnitOfWork(database.session_factory()) as work:
        result = await DeliverDigest(
            work.delivery, Gateway(), lambda: NOW, lambda _: ("part",)
        ).execute(value)
    assert result is DeliveryState.SENT
    assert observed == [("sending", "sending", "sending")]


async def test_crash_after_dispatch_preserves_claim_and_stops_rerun(
    database: Database,
) -> None:
    value = await create_digest(database)
    calls = 0

    class CrashingGateway:
        async def send(self, content: str) -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError("simulated process crash")

    with pytest.raises(RuntimeError, match="simulated process crash"):
        async with SqlAlchemyDeliveryUnitOfWork(database.session_factory()) as work:
            await DeliverDigest(
                work.delivery,
                CrashingGateway(),
                lambda: NOW,
                lambda _: ("part",),
            ).execute(value)

    async with database.session() as session:
        digest_row = await session.scalar(select(JobDigestModel))
        part_row = await session.scalar(select(JobDigestDeliveryPartModel))
        attempt_row = await session.scalar(select(JobDigestDeliveryAttemptModel))
        assert digest_row is not None and digest_row.status == "sending"
        assert part_row is not None and part_row.state == "sending"
        assert attempt_row is not None and attempt_row.state == "sending"

    class ShouldNotSend:
        async def send(self, content: str) -> str:
            raise AssertionError("rerun must not call the gateway")

    async with SqlAlchemyDeliveryUnitOfWork(database.session_factory()) as work:
        result = await DeliverDigest(
            work.delivery, ShouldNotSend(), lambda: NOW, lambda _: ("part",)
        ).execute(value)
    assert result is DeliveryState.UNCERTAIN
    assert calls == 1


async def test_concurrent_delivery_workers_make_at_most_one_gateway_call(
    database: Database,
) -> None:
    value = await create_digest(database)
    calls = 0
    call_lock = asyncio.Lock()

    class Gateway:
        async def send(self, content: str) -> str:
            nonlocal calls
            async with call_lock:
                calls += 1
            await asyncio.sleep(0)
            return "42"

    async def worker() -> DeliveryState:
        async with SqlAlchemyDeliveryUnitOfWork(database.session_factory()) as work:
            return await DeliverDigest(
                work.delivery, Gateway(), lambda: NOW, lambda _: ("part",)
            ).execute(value)

    results = await asyncio.gather(worker(), worker())
    assert calls == 1
    assert DeliveryState.SENT in results
