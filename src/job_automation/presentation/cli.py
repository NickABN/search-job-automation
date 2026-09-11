"""Greenhouse ingestion command for one or all configured public boards."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import cast

from job_automation.application.ingestion import IngestionUnitOfWork, IngestJobs
from job_automation.config import GreenhouseBoard, get_settings
from job_automation.domain.jobs import IngestionRun, utc_now
from job_automation.infrastructure.database import Database
from job_automation.infrastructure.greenhouse import GreenhouseJobSource
from job_automation.infrastructure.ingestion import SqlAlchemyIngestionUnitOfWork


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest configured Greenhouse boards")
    parser.add_argument(
        "--board-token", help="Ingest one explicit Greenhouse board identifier"
    )
    parser.add_argument("--company", help="Explicit company name")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        if (args.board_token is None) != (args.company is None):
            raise ValueError("--board-token and --company must be provided together")
        boards = (
            (GreenhouseBoard(board_token=args.board_token, company=args.company),)
            if args.board_token is not None
            else settings.greenhouse_boards
        )
        succeeded = 0
        for board in boards:
            try:
                run = await _ingest_board(database, board)
            except Exception:
                print(f"{board.company}: failed", file=sys.stderr)
                continue
            print(
                f"{board.company}: {run.status.value}: fetched={run.fetched_count} "
                f"created={run.created_count} updated={run.updated_count} "
                f"unchanged={run.unchanged_count}"
            )
            succeeded += run.status.value == "succeeded"
        return 0 if succeeded else 1
    finally:
        await database.dispose()


async def _ingest_board(database: Database, board: GreenhouseBoard) -> IngestionRun:
    source = GreenhouseJobSource(board.board_token, board.company)
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
        return await use_case.execute()
    finally:
        await source.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except Exception:
        print("greenhouse ingestion failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
