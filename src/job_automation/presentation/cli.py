"""Manual Greenhouse ingestion command."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import cast

from job_automation.application.ingestion import IngestionUnitOfWork, IngestJobs
from job_automation.config import get_settings
from job_automation.domain.jobs import utc_now
from job_automation.infrastructure.database import Database
from job_automation.infrastructure.greenhouse import GreenhouseJobSource
from job_automation.infrastructure.ingestion import SqlAlchemyIngestionUnitOfWork


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest one public Greenhouse job board"
    )
    parser.add_argument(
        "--board-token", required=True, help="Greenhouse board identifier"
    )
    parser.add_argument("--company", required=True, help="Explicit company name")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        source = GreenhouseJobSource(args.board_token, args.company)
        try:
            use_case = IngestJobs(
                source=source,
                unit_of_work_factory=lambda: cast(
                    IngestionUnitOfWork,
                    SqlAlchemyIngestionUnitOfWork(database.session_factory()),
                ),
                clock=utc_now,
                source_name=source.source_identity,
            )
            run = await use_case.execute()
        finally:
            await source.aclose()
        print(
            f"{run.status.value}: fetched={run.fetched_count} "
            f"created={run.created_count} updated={run.updated_count} "
            f"unchanged={run.unchanged_count}"
        )
        return 0 if run.status.value == "succeeded" else 1
    finally:
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except Exception:
        print("greenhouse ingestion failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
