"""Safe presentation command for deterministic job ranking."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import cast

from job_automation.application.ranking import RankingUnitOfWork, RankJobs
from job_automation.config import get_settings
from job_automation.domain.jobs import utc_now
from job_automation.domain.ranking import RankingPolicy
from job_automation.infrastructure.database import Database
from job_automation.infrastructure.ranking import SqlAlchemyRankingUnitOfWork


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rank persisted jobs with explanations"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum eligible jobs to print (1-1000)",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        limit = settings.ranking_limit if args.limit is None else args.limit
        results = await RankJobs(
            lambda: cast(
                RankingUnitOfWork,
                SqlAlchemyRankingUnitOfWork(database.session_factory()),
            ),
            RankingPolicy(settings.ranking_profile()),
            utc_now,
        ).execute(limit)
        for result in results:
            reasons = "; ".join(result.evaluation.explanations[:2])
            print(
                f"{result.evaluation.score}\t{result.job.title}\t"
                f"{result.job.company}\t"
                f"{result.job.location_text or 'Unknown'}\t{reasons}"
            )
        return 0
    finally:
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except Exception:
        print("job ranking failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
