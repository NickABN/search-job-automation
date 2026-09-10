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
async def test_delivery_resumes_confirmed_parts_and_stops_on_uncertain() -> None:
    class Store:
        def __init__(self) -> None:
            self.sent: list[int] = []

        async def prepare_parts(self, digest, parts):
            return [
                DeliveryPart(digest.id, 0, parts[0], "a", DeliveryState.SENT),
                DeliveryPart(digest.id, 1, parts[1], "b"),
            ]

        async def mark_sending(self, part, attempted_at):
            return part

        async def mark_sent(self, part, provider_message_id, sent_at):
            self.sent.append(part.part_index)

        async def mark_failed(self, part, state, error_category, failed_at):
            pass

        async def mark_digest_sent(self, digest, sent_at):
            raise AssertionError("uncertain must not complete")

    class Gateway:
        async def send(self, content):
            raise DeliveryError(DeliveryState.UNCERTAIN, "post_dispatch_timeout")

    result = await DeliverDigest(
        Store(), Gateway(), lambda: DIGEST.scheduled_at, lambda _: ("one", "two")
    ).execute(DIGEST)
    assert result is DeliveryState.UNCERTAIN
