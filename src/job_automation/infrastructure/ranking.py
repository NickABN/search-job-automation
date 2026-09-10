"""SQLAlchemy adapters for ranking."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_automation.domain.ranking import (
    JobListing,
    RankingEvaluation,
)
from job_automation.infrastructure.models import JobEvaluationModel, JobModel


def _listing(model: JobModel) -> JobListing:
    return JobListing(
        str(model.id),
        model.title,
        model.company,
        model.description,
        model.location_text,
        model.published_at,
        model.source_updated_at,
    )


class SqlAlchemyJobReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_jobs(self) -> list[JobListing]:
        result = await self.session.scalars(select(JobModel).order_by(JobModel.id))
        return [_listing(model) for model in result]


class SqlAlchemyEvaluationStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_evaluation(self, job_id: str, evaluation: RankingEvaluation) -> None:
        model = await self.session.scalar(
            select(JobEvaluationModel).where(
                JobEvaluationModel.job_id == job_id,
                JobEvaluationModel.profile_identifier == evaluation.profile_identifier,
                JobEvaluationModel.policy_version == evaluation.policy_version,
            )
        )
        classification = evaluation.classification
        values: dict[str, object] = {
            "job_id": job_id,
            "profile_identifier": evaluation.profile_identifier,
            "policy_version": evaluation.policy_version,
            "eligible": evaluation.eligible,
            "score": evaluation.score,
            "classification": {
                "role_family": classification.role_family.value,
                "seniority": classification.seniority.value,
                "work_model": classification.work_model.value,
                "matched_skills": list(classification.matched_skills),
                "years_required": classification.years_required,
                "english_requirement": classification.english_requirement,
                "salary": {
                    "minimum_monthly_mxn": classification.salary.minimum_monthly_mxn,
                    "maximum_monthly_mxn": classification.salary.maximum_monthly_mxn,
                    "reason": classification.salary.reason,
                },
            },
            "factors": [
                {
                    "name": factor.name,
                    "points": factor.points,
                    "maximum": factor.maximum,
                    "reason": factor.reason,
                }
                for factor in evaluation.factors
            ],
            "explanations": list(evaluation.explanations),
            "exclusion_reasons": list(evaluation.exclusion_reasons),
            "evaluated_at": evaluation.evaluated_at,
        }
        if model is None:
            self.session.add(JobEvaluationModel(**values))
        else:
            for key, value in values.items():
                setattr(model, key, value)


class SqlAlchemyRankingUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.jobs = SqlAlchemyJobReader(session)
        self.evaluations = SqlAlchemyEvaluationStore(session)

    async def __aenter__(self) -> "SqlAlchemyRankingUnitOfWork":
        await self.session.begin()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
        await self.session.close()
