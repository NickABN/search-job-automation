"""PostgreSQL adapter for atomic digest preparation."""

from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from job_automation.domain.digests import (
    DigestItem,
    DigestSlot,
    DigestStatus,
    JobDigest,
)
from job_automation.infrastructure.models import (
    JobDigestItemModel,
    JobDigestModel,
    JobEvaluationModel,
    JobModel,
)


def _domain(model: JobDigestModel, items: list[JobDigestItemModel]) -> JobDigest:
    return JobDigest(
        str(model.id),
        model.local_date,
        DigestSlot(model.slot),
        model.scheduled_at,
        DigestStatus(model.status),
        tuple(
            DigestItem(
                item.job_id.__str__(),
                item.title,
                item.company,
                item.location,
                item.canonical_url,
                item.score,
                item.role_family,
                tuple(item.reasons),
            )
            for item in sorted(items, key=lambda value: value.item_index)
        ),
    )


class SqlAlchemyDigestStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def prepare(
        self,
        local_date: date,
        slot: DigestSlot,
        scheduled_at: datetime,
        threshold: int,
        max_jobs: int,
    ) -> JobDigest:
        key = "job-digest-selection"
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )
        existing = await self.session.scalar(
            select(JobDigestModel).where(
                JobDigestModel.local_date == local_date,
                JobDigestModel.slot == slot.value,
            )
        )
        if existing is not None:
            items = list(
                (
                    await self.session.scalars(
                        select(JobDigestItemModel).where(
                            JobDigestItemModel.digest_id == existing.id
                        )
                    )
                ).all()
            )
            return _domain(existing, items)

        claimed = (
            select(JobDigestItemModel.job_id)
            .join(JobDigestModel, JobDigestModel.id == JobDigestItemModel.digest_id)
            .where(JobDigestModel.status.in_(["prepared", "sending", "sent"]))
        )
        candidates = (
            await self.session.execute(
                select(JobModel, JobEvaluationModel)
                .join(JobEvaluationModel, JobEvaluationModel.job_id == JobModel.id)
                .where(
                    JobEvaluationModel.eligible.is_(True),
                    JobEvaluationModel.score >= threshold,
                    ~JobModel.id.in_(claimed),
                )
                .order_by(
                    JobEvaluationModel.score.desc(),
                    JobModel.company.asc(),
                    JobModel.title.asc(),
                    JobModel.id.asc(),
                )
                .limit(max_jobs)
            )
        ).all()
        status = DigestStatus.PREPARED if candidates else DigestStatus.EMPTY
        model = JobDigestModel(
            local_date=local_date,
            slot=slot.value,
            scheduled_at=scheduled_at,
            status=status.value,
        )
        self.session.add(model)
        await self.session.flush()
        for index, (job, evaluation) in enumerate(candidates):
            classification = evaluation.classification
            self.session.add(
                JobDigestItemModel(
                    digest_id=model.id,
                    job_id=job.id,
                    item_index=index,
                    title=job.title,
                    company=job.company,
                    location=job.location_text or "Unknown",
                    canonical_url=job.canonical_url,
                    score=evaluation.score,
                    role_family=str(classification.get("role_family", "unknown")),
                    reasons=list(evaluation.explanations)[:3],
                )
            )
        await self.session.flush()
        return _domain(
            model,
            list(
                (
                    await self.session.scalars(
                        select(JobDigestItemModel).where(
                            JobDigestItemModel.digest_id == model.id
                        )
                    )
                ).all()
            ),
        )


class SqlAlchemyDigestUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.digests = SqlAlchemyDigestStore(session)

    async def __aenter__(self) -> "SqlAlchemyDigestUnitOfWork":
        await self.session.begin()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
        await self.session.close()
