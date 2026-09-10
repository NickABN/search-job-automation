"""SQLAlchemy adapter for resumable delivery state."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_automation.application.notifications import DeliveryPart, DeliveryState
from job_automation.domain.digests import DigestStatus, JobDigest
from job_automation.infrastructure.models import (
    JobDigestDeliveryPartModel,
    JobDigestModel,
)


def _part(model: JobDigestDeliveryPartModel) -> DeliveryPart:
    return DeliveryPart(
        str(model.digest_id),
        model.part_index,
        model.content,
        model.content_hash,
        DeliveryState(model.state),
        model.attempt_count,
        model.provider_message_id,
        model.error_category,
    )


class SqlAlchemyDeliveryStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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

            now = datetime.now().astimezone()
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

    async def mark_sending(
        self, part: DeliveryPart, attempted_at: datetime
    ) -> DeliveryPart:
        model = await self.session.scalar(
            select(JobDigestDeliveryPartModel).where(
                JobDigestDeliveryPartModel.digest_id == part.digest_id,
                JobDigestDeliveryPartModel.part_index == part.part_index,
            )
        )
        assert model is not None
        model.state = DeliveryState.SENDING.value
        model.attempt_count += 1
        model.updated_at = attempted_at
        return _part(model)

    async def mark_sent(
        self, part: DeliveryPart, provider_message_id: str, sent_at: datetime
    ) -> None:
        model = await self.session.scalar(
            select(JobDigestDeliveryPartModel).where(
                JobDigestDeliveryPartModel.digest_id == part.digest_id,
                JobDigestDeliveryPartModel.part_index == part.part_index,
            )
        )
        assert model is not None
        model.state = DeliveryState.SENT.value
        model.provider_message_id = provider_message_id
        model.updated_at = sent_at

    async def mark_failed(
        self,
        part: DeliveryPart,
        state: DeliveryState,
        error_category: str,
        failed_at: datetime,
    ) -> None:
        model = await self.session.scalar(
            select(JobDigestDeliveryPartModel).where(
                JobDigestDeliveryPartModel.digest_id == part.digest_id,
                JobDigestDeliveryPartModel.part_index == part.part_index,
            )
        )
        assert model is not None
        model.state = state.value
        model.error_category = error_category
        model.updated_at = failed_at

    async def mark_digest_sent(self, digest: JobDigest, sent_at: datetime) -> None:
        model = await self.session.get(JobDigestModel, digest.id)
        assert model is not None
        model.status = DigestStatus.SENT.value


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
