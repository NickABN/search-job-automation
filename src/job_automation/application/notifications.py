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


class DeliveryTransaction(DeliveryStore, Protocol):
    async def __aenter__(self) -> "DeliveryTransaction": ...
    async def __aexit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class DeliverDigest:
    transaction_factory: Callable[[], DeliveryTransaction]
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
        async with self.transaction_factory() as transaction:
            existing_state = await transaction.claim_digest_sending(
                digest, self.clock()
            )
            if existing_state is not None:
                return (
                    DeliveryState.SENT
                    if existing_state is DigestStatus.SENT
                    else DeliveryState.UNCERTAIN
                )
            parts = await transaction.prepare_parts(digest, self.render(digest))
            marked = await self._claim_first(transaction, parts)
        if marked is None and any(
            part.state in {DeliveryState.SENDING, DeliveryState.UNCERTAIN}
            for part in parts
        ):
            return DeliveryState.UNCERTAIN
        for part in parts:
            if part.state is DeliveryState.SENT:
                continue
            if marked is None:
                async with self.transaction_factory() as transaction:
                    marked = await transaction.claim_sending(part, self.clock())
                if marked is None:
                    return DeliveryState.UNCERTAIN
            try:
                message_id = await self.gateway.send(marked.content)
            except DeliveryError as error:
                async with self.transaction_factory() as transaction:
                    await transaction.mark_failed(
                        marked, error.state, error.category, self.clock()
                    )
                    await transaction.mark_digest_state(
                        digest,
                        DigestStatus.UNCERTAIN
                        if error.state is DeliveryState.UNCERTAIN
                        else DigestStatus.FAILED,
                        self.clock(),
                    )
                return error.state
            async with self.transaction_factory() as transaction:
                await transaction.mark_sent(marked, message_id, self.clock())
            marked = None
        async with self.transaction_factory() as transaction:
            await transaction.mark_digest_state(digest, DigestStatus.SENT, self.clock())
        return DeliveryState.SENT

    async def _claim_first(
        self, transaction: DeliveryTransaction, parts: Sequence[DeliveryPart]
    ) -> DeliveryPart | None:
        for part in parts:
            if part.state is DeliveryState.SENT:
                continue
            if part.state in {DeliveryState.SENDING, DeliveryState.UNCERTAIN}:
                return None
            return await transaction.claim_sending(part, self.clock())
        return None


class DeliveryError(Exception):
    def __init__(self, state: DeliveryState, category: str) -> None:
        super().__init__(category)
        self.state = state
        self.category = category
