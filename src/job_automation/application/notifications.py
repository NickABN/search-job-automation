"""Resumable notification delivery ports and use case."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from job_automation.domain.digests import DigestStatus, JobDigest


class DeliveryState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    PERMANENT_FAILED = "permanent_failed"
    UNCERTAIN = "uncertain"
    NOOP = "noop"


@dataclass(frozen=True, slots=True)
class DeliveryPart:
    digest_id: str
    part_index: int
    content: str
    content_hash: str
    state: DeliveryState = DeliveryState.PENDING
    attempt_count: int = 0
    provider_message_id: str | None = None
    error_category: str | None = None
    attempt_id: str | None = None


class NotificationGateway(Protocol):
    async def send(self, content: str) -> str: ...


class DeliveryStore(Protocol):
    async def prepare_parts(
        self, digest: JobDigest, parts: Sequence[str]
    ) -> Sequence[DeliveryPart]: ...
    async def claim_sending(
        self, part: DeliveryPart, attempted_at: datetime
    ) -> DeliveryPart | None: ...
    async def mark_sent(
        self, part: DeliveryPart, provider_message_id: str, sent_at: datetime
    ) -> None: ...
    async def mark_failed(
        self,
        part: DeliveryPart,
        state: DeliveryState,
        error_category: str,
        failed_at: datetime,
    ) -> None: ...
    async def mark_digest_state(
        self, digest: JobDigest, state: DigestStatus, changed_at: datetime
    ) -> None: ...
    async def claim_digest_sending(
        self, digest: JobDigest, changed_at: datetime
    ) -> DigestStatus | None: ...


@dataclass(frozen=True, slots=True)
class DeliverDigest:
    store: DeliveryStore
    gateway: NotificationGateway
    clock: Callable[[], datetime]
    render: Callable[[JobDigest], Sequence[str]]

    async def execute(self, digest: JobDigest) -> DeliveryState:
        if digest.status is DigestStatus.EMPTY:
            return DeliveryState.NOOP
        if digest.status in {
            DigestStatus.SENT,
            DigestStatus.FAILED,
            DigestStatus.UNCERTAIN,
        }:
            return DeliveryState(digest.status.value)
        existing_state = await self.store.claim_digest_sending(digest, self.clock())
        if existing_state is not None:
            if existing_state is DigestStatus.SENT:
                return DeliveryState.SENT
            await self.store.mark_digest_state(
                digest, DigestStatus.UNCERTAIN, self.clock()
            )
            return DeliveryState.UNCERTAIN
        parts = await self.store.prepare_parts(digest, self.render(digest))
        for part in parts:
            if part.state is DeliveryState.SENT:
                continue
            if part.state in {DeliveryState.SENDING, DeliveryState.UNCERTAIN}:
                await self.store.mark_digest_state(
                    digest, DigestStatus.UNCERTAIN, self.clock()
                )
                return DeliveryState.UNCERTAIN
            marked = await self.store.claim_sending(part, self.clock())
            if marked is None:
                await self.store.mark_digest_state(
                    digest, DigestStatus.UNCERTAIN, self.clock()
                )
                return DeliveryState.UNCERTAIN
            try:
                message_id = await self.gateway.send(marked.content)
            except DeliveryError as error:
                await self.store.mark_failed(
                    marked, error.state, error.category, self.clock()
                )
                await self.store.mark_digest_state(
                    digest,
                    DigestStatus.UNCERTAIN
                    if error.state is DeliveryState.UNCERTAIN
                    else DigestStatus.FAILED,
                    self.clock(),
                )
                return error.state
            await self.store.mark_sent(marked, message_id, self.clock())
        await self.store.mark_digest_state(digest, DigestStatus.SENT, self.clock())
        return DeliveryState.SENT


class DeliveryError(Exception):
    def __init__(self, state: DeliveryState, category: str) -> None:
        super().__init__(category)
        self.state = state
        self.category = category
