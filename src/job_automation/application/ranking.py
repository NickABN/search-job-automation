"""Ranking use case and ports."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from job_automation.domain.ranking import JobListing, RankingEvaluation, RankingPolicy


class JobReader(Protocol):
    async def list_jobs(self) -> Sequence[JobListing]: ...


class EvaluationStore(Protocol):
    async def save_evaluation(
        self, job_id: str, evaluation: RankingEvaluation
    ) -> None: ...


class RankingUnitOfWork(Protocol):
    jobs: JobReader
    evaluations: EvaluationStore

    async def __aenter__(self) -> "RankingUnitOfWork": ...
    async def __aexit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class RankedJob:
    job: JobListing
    evaluation: RankingEvaluation


class RankJobs:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], RankingUnitOfWork],
        policy: RankingPolicy,
        clock: Callable[[], datetime],
    ) -> None:
        self._factory = unit_of_work_factory
        self._policy = policy
        self._clock = clock

    async def execute(self, limit: int = 20) -> list[RankedJob]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        evaluated_at = self._clock()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        async with self._factory() as work:
            ranked = [
                (job, self._policy.evaluate(job, evaluated_at))
                for job in await work.jobs.list_jobs()
            ]
            for job, evaluation in ranked:
                await work.evaluations.save_evaluation(job.id, evaluation)
        return [
            RankedJob(job, evaluation)
            for job, evaluation in sorted(
                ranked,
                key=lambda item: (
                    -item[1].eligible,
                    -item[1].score,
                    item[0].company.casefold(),
                    item[0].title.casefold(),
                    item[0].id,
                ),
            )
            if evaluation.eligible
        ][:limit]
