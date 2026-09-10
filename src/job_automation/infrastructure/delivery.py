"""SQLAlchemy adapter for transactionally claimed delivery state."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_automation.application.notifications import DeliveryPart, DeliveryState
from job_automation.domain.digests import DigestStatus, JobDigest
from job_automation.infrastructure.models import (
    JobDigestDeliveryAttemptModel,
    JobDigestDeliveryPartModel,
    JobDigestModel,
)


def _part(
    model: JobDigestDeliveryPartModel, attempt_id: str | None = None
) -> DeliveryPart:
    return DeliveryPart(
        str(model.digest_id),
        model.part_index,
        model.content,
        model.content_hash,
        DeliveryState(model.state),
        model.attempt_count,
        model.provider_message_id,
        model.error_category,
        attempt_id,
    )


class SqlAlchemyDeliveryStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_digest_sending(
        self, digest: JobDigest, changed_at: datetime
    ) -> DigestStatus | None:
        model = await self.session.scalar(
            select(JobDigestModel)
            .where(JobDigestModel.id == digest.id)
            .with_for_update()
        )
        if model is None:
            return DigestStatus.UNCERTAIN
        if model.status != DigestStatus.PREPARED.value:
            return DigestStatus(model.status)
        model.status = DigestStatus.SENDING.value
        return None

    async def prepare_parts(
        self, digest: JobDigest, parts: Sequence[str]
    ) -> Sequence[DeliveryPart]:
        existing = list(
            (
                await self.session.scalars(
                    select(JobDigestDeliveryPartModel)
                    .where(JobDigestDeliveryPartModel.digest_id == digest.id)
                    .order_by(JobDigestDeliveryPartModel.part_index)
                )
            ).all()
        )
        if not existing:
            from job_automation.infrastructure.telegram import content_hash

            now = datetime.now(UTC)
            for index, content in enumerate(parts):
                self.session.add(
                    JobDigestDeliveryPartModel(
                        digest_id=digest.id,
                        part_index=index,
                        content=content,
                        content_hash=content_hash(content),
                        state=DeliveryState.PENDING.value,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await self.session.flush()
            existing = list(
                (
                    await self.session.scalars(
                        select(JobDigestDeliveryPartModel)
                        .where(JobDigestDeliveryPartModel.digest_id == digest.id)
                        .order_by(JobDigestDeliveryPartModel.part_index)
                    )
                ).all()
            )
        return [_part(model) for model in existing]

    async def claim_sending(
        self, part: DeliveryPart, attempted_at: datetime
    ) -> DeliveryPart | None:
        model = await self.session.scalar(
            select(JobDigestDeliveryPartModel)
            .where(
                JobDigestDeliveryPartModel.digest_id == part.digest_id,
                JobDigestDeliveryPartModel.part_index == part.part_index,
            )
            .with_for_update()
        )
        if model is None or model.state != DeliveryState.PENDING.value:
            return None
        model.state = DeliveryState.SENDING.value
        model.attempt_count += 1
        model.updated_at = attempted_at
        attempt = JobDigestDeliveryAttemptModel(
            part_id=model.id,
            attempted_at=attempted_at,
            state=DeliveryState.SENDING.value,
        )
        self.session.add(attempt)
        await self.session.flush()
        return _part(model, str(attempt.id))

    async def mark_sent(
        self, part: DeliveryPart, provider_message_id: str, sent_at: datetime
    ) -> None:
        model = await self._get_part(part)
        model.state = DeliveryState.SENT.value
        model.provider_message_id = provider_message_id
        model.updated_at = sent_at
        attempt = await self._get_attempt(part)
        attempt.state = DeliveryState.SENT.value
        attempt.provider_message_id = provider_message_id
        attempt.completed_at = sent_at

    async def mark_failed(
        self,
        part: DeliveryPart,
        state: DeliveryState,
        error_category: str,
        failed_at: datetime,
    ) -> None:
        model = await self._get_part(part)
        model.state = state.value
        model.error_category = error_category
        model.updated_at = failed_at
        attempt = await self._get_attempt(part)
        attempt.state = state.value
        attempt.error_category = error_category
        attempt.completed_at = failed_at

    async def mark_digest_state(
        self, digest: JobDigest, state: DigestStatus, changed_at: datetime
    ) -> None:
        model = await self.session.get(JobDigestModel, digest.id)
        assert model is not None
        model.status = state.value
        if state is DigestStatus.SENT:
            model.sent_at = changed_at

    async def _get_part(self, part: DeliveryPart) -> JobDigestDeliveryPartModel:
        model = await self.session.scalar(
            select(JobDigestDeliveryPartModel).where(
                JobDigestDeliveryPartModel.digest_id == part.digest_id,
                JobDigestDeliveryPartModel.part_index == part.part_index,
            )
        )
        assert model is not None
        return model

    async def _get_attempt(self, part: DeliveryPart) -> JobDigestDeliveryAttemptModel:
        assert part.attempt_id is not None
        model = await self.session.get(JobDigestDeliveryAttemptModel, part.attempt_id)
        assert model is not None
        return model


class SqlAlchemyDeliveryUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.delivery = SqlAlchemyDeliveryStore(session)

    async def __aenter__(self) -> "SqlAlchemyDeliveryUnitOfWork":
        await self.session.begin()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
        await self.session.close()
