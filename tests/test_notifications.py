from datetime import UTC, date, datetime

import httpx
import pytest

from job_automation.application.notifications import (
    DeliverDigest,
    DeliveryError,
    DeliveryPart,
    DeliveryState,
)
from job_automation.domain.digests import (
    DigestItem,
    DigestSlot,
    DigestStatus,
    JobDigest,
)
from job_automation.infrastructure.telegram import (
    TelegramGateway,
    content_hash,
    render_digest,
)

DIGEST = JobDigest(
    "digest-1",
    date(2026, 9, 10),
    DigestSlot.MORNING,
    datetime(2026, 9, 10, 15, tzinfo=UTC),
    DigestStatus.PREPARED,
    (
        DigestItem(
            "job-1",
            "<Engineer>",
            "Acme & Co",
            "Remote",
            "https://example.test/job",
            88,
            "backend",
            ("Good <match>",),
        ),
    ),
)


def test_rendering_escapes_and_hash_is_stable() -> None:
    parts = render_digest(DIGEST)
    assert "&lt;Engineer&gt;" in parts[0]
    assert "Acme &amp; Co" in parts[0]
    assert len(parts[0]) <= 4096
    assert content_hash(parts[0]) == content_hash(parts[0])


def test_renderer_does_not_link_unsafe_or_pathological_urls() -> None:
    digest = JobDigest(
        DIGEST.id,
        DIGEST.local_date,
        DIGEST.slot,
        DIGEST.scheduled_at,
        DIGEST.status,
        (
            DigestItem(
                "job-1",
                "x" * 10_000,
                "company & <x>",
                "remote",
                "javascript:alert(1)",
                80,
                "backend",
                ("reason & <x>",) * 20,
            ),
        ),
    )
    part = render_digest(digest)[0]
    assert "<a " not in part
    assert "javascript:" not in part
    assert "&amp;" in part
    assert len(part) <= 4096
    assert part.count("<b>") == part.count("</b>")


@pytest.mark.asyncio
async def test_gateway_success_returns_message_id_without_network() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendMessage")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    gateway = TelegramGateway(
        "secret-token",
        "chat",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await gateway.send("<b>safe</b>") == "42"
    await gateway.aclose()


@pytest.mark.asyncio
async def test_gateway_retry_boundaries_are_conservative() -> None:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    responses = iter(
        [
            httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"ok": False},
            ),
            httpx.Response(503, json={"ok": False, "description": "secret body"}),
        ]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    gateway = TelegramGateway(
        "secret-token",
        "chat",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=sleep,
    )
    with pytest.raises(DeliveryError) as error:
        await gateway.send("safe")
    assert error.value.state is DeliveryState.UNCERTAIN
    assert error.value.category == "provider_5xx"
    assert sleeps == [0]
    assert "secret" not in str(error.value)
    await gateway.aclose()


@pytest.mark.asyncio
async def test_delivery_resumes_confirmed_parts_and_stops_on_uncertain() -> None:
    class Store:
        def __init__(self) -> None:
            self.sent: list[int] = []

        async def prepare_parts(self, digest, parts):
            return [
                DeliveryPart(digest.id, 0, parts[0], "a", DeliveryState.SENT),
                DeliveryPart(digest.id, 1, parts[1], "b"),
            ]

        async def claim_digest_sending(self, digest, changed_at):
            return None

        async def claim_sending(self, part, attempted_at):
            return part

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def mark_sent(self, part, provider_message_id, sent_at):
            self.sent.append(part.part_index)

        async def mark_failed(self, part, state, error_category, failed_at):
            pass

        async def mark_digest_state(self, digest, state, changed_at):
            assert state is DigestStatus.UNCERTAIN

    class Gateway:
        async def send(self, content):
            raise DeliveryError(DeliveryState.UNCERTAIN, "post_dispatch_timeout")

    result = await DeliverDigest(
        Store,
        Gateway(),
        lambda: DIGEST.scheduled_at,
        lambda _: ("one", "two"),
    ).execute(DIGEST)
    assert result is DeliveryState.UNCERTAIN


@pytest.mark.asyncio
async def test_empty_digest_is_noop_without_gateway() -> None:
    empty = JobDigest(
        "empty",
        date(2026, 9, 10),
        DigestSlot.MORNING,
        datetime(2026, 9, 10, 15, tzinfo=UTC),
        DigestStatus.EMPTY,
        (),
    )

    class Store:
        pass

    result = await DeliverDigest(
        Store, None, lambda: empty.scheduled_at, render_digest
    ).execute(empty)  # type: ignore[arg-type]
    assert result is DeliveryState.NOOP


@pytest.mark.asyncio
async def test_gateway_runs_between_closed_fresh_transactions() -> None:
    transactions = []

    class Transaction:
        def __init__(self) -> None:
            self.closed = False
            self.part = DeliveryPart(DIGEST.id, 0, "part", "hash")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def claim_digest_sending(self, digest, changed_at):
            return None

        async def prepare_parts(self, digest, parts):
            return (self.part,)

        async def claim_sending(self, part, attempted_at):
            return part

        async def mark_sent(self, part, provider_message_id, sent_at):
            pass

        async def mark_failed(self, part, state, error_category, failed_at):
            pass

        async def mark_digest_state(self, digest, state, changed_at):
            pass

    def factory():
        transaction = Transaction()
        transactions.append(transaction)
        return transaction

    class Gateway:
        async def send(self, content):
            assert transactions
            assert all(transaction.closed for transaction in transactions)
            return "42"

    result = await DeliverDigest(
        factory, Gateway(), lambda: DIGEST.scheduled_at, lambda _: ("part",)
    ).execute(DIGEST)
    assert result is DeliveryState.SENT
    assert len(transactions) == 3
    assert len({id(transaction) for transaction in transactions}) == 3
