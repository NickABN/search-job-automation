"""SQLAlchemy adapters for the ingestion application ports."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_automation.application.ingestion import ObservationOutcome
from job_automation.domain.jobs import IngestionRun, NormalizedJobObservation
from job_automation.infrastructure.models import (
    IngestionRunModel,
    JobModel,
    JobObservationModel,
    SourceModel,
)


def _now() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyObservationStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self, observation: NormalizedJobObservation, raw_payload: dict[str, object]
    ) -> ObservationOutcome:
        source = await self.session.scalar(
            select(SourceModel).where(SourceModel.identity == observation.source)
        )
        if source is None:
            source = SourceModel(identity=observation.source, created_at=_now())
            self.session.add(source)
            await self.session.flush()

        job = await self.session.scalar(
            select(JobModel).where(
                JobModel.source_id == source.id,
                JobModel.source_job_id == observation.source_job_id,
            )
        )
        if job is None:
            job = JobModel(
                source_id=source.id,
                source_job_id=observation.source_job_id,
                title=observation.title,
                company=observation.company,
                description=observation.description,
                canonical_url=observation.canonical_url,
                source_url=observation.source_url,
                location_text=observation.location_text,
                published_at=observation.published_at,
                source_updated_at=observation.source_updated_at,
                first_seen_at=observation.observed_at,
                last_seen_at=observation.observed_at,
                current_content_hash=observation.content_hash,
            )
            self.session.add(job)
            await self.session.flush()
            self.session.add(
                JobObservationModel(
                    job_id=job.id,
                    observed_at=observation.observed_at,
                    content_hash=observation.content_hash,
                    raw_payload=raw_payload,
                )
            )
            return ObservationOutcome.CREATED

        if observation.observed_at > job.last_seen_at:
            job.last_seen_at = observation.observed_at
        if job.current_content_hash == observation.content_hash:
            return ObservationOutcome.UNCHANGED

        job.title = observation.title
        job.company = observation.company
        job.description = observation.description
        job.canonical_url = observation.canonical_url
        job.source_url = observation.source_url
        job.location_text = observation.location_text
        job.published_at = observation.published_at
        job.source_updated_at = observation.source_updated_at
        job.current_content_hash = observation.content_hash
        historical_observation = await self.session.scalar(
            select(JobObservationModel.id).where(
                JobObservationModel.job_id == job.id,
                JobObservationModel.content_hash == observation.content_hash,
            )
        )
        if historical_observation is None:
            self.session.add(
                JobObservationModel(
                    job_id=job.id,
                    observed_at=observation.observed_at,
                    content_hash=observation.content_hash,
                    raw_payload=raw_payload,
                )
            )
        return ObservationOutcome.UPDATED


class SqlAlchemyIngestionRunStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, run: IngestionRun) -> None:
        source = await self.session.scalar(
            select(SourceModel).where(SourceModel.identity == run.source)
        )
        if source is None:
            source = SourceModel(identity=run.source, created_at=_now())
            self.session.add(source)
            await self.session.flush()
        model = await self.session.scalar(
            select(IngestionRunModel).where(
                IngestionRunModel.source_id == source.id,
                IngestionRunModel.started_at == run.started_at,
            )
        )
        values = dict(
            source_id=source.id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status.value,
            fetched_count=run.fetched_count,
            created_count=run.created_count,
            updated_count=run.updated_count,
            unchanged_count=run.unchanged_count,
            error_summary=run.error_summary,
        )
        if model is None:
            self.session.add(IngestionRunModel(**values))
        else:
            for key, value in values.items():
                if key != "source_id":
                    setattr(model, key, value)


class SqlAlchemyIngestionUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.observations = SqlAlchemyObservationStore(session)
        self.runs = SqlAlchemyIngestionRunStore(session)

    async def __aenter__(self) -> "SqlAlchemyIngestionUnitOfWork":
        await self.session.begin()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
        await self.session.close()
