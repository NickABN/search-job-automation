"""Bounded database readiness command for scheduled jobs."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence

from job_automation.application.readiness import (
    MAX_ATTEMPT_TIMEOUT_SECONDS,
    MAX_ATTEMPTS,
    MAX_DELAY_SECONDS,
    MIN_ATTEMPT_TIMEOUT_SECONDS,
    MIN_ATTEMPTS,
    MIN_DELAY_SECONDS,
    wait_for_readiness,
)
from job_automation.config import get_settings
from job_automation.infrastructure.database import (
    Database,
    SqlAlchemyReadinessProbe,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wait for PostgreSQL readiness")
    parser.add_argument(
        "--attempts",
        type=_bounded_int(MIN_ATTEMPTS, MAX_ATTEMPTS, "attempts"),
        default=6,
    )
    parser.add_argument(
        "--attempt-timeout",
        type=_bounded_float(
            MIN_ATTEMPT_TIMEOUT_SECONDS,
            MAX_ATTEMPT_TIMEOUT_SECONDS,
            "attempt timeout",
        ),
        default=5.0,
    )
    parser.add_argument(
        "--delay",
        type=_bounded_float(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS, "retry delay"),
        default=2.0,
    )
    return parser


def _bounded_int(lower: int, upper: int, label: str) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{label} must be an integer") from error
        if not lower <= parsed <= upper:
            raise argparse.ArgumentTypeError(
                f"{label} must be between {lower} and {upper}"
            )
        return parsed

    return parse


def _bounded_float(lower: float, upper: float, label: str) -> Callable[[str], float]:
    def parse(value: str) -> float:
        try:
            parsed = float(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{label} must be a number") from error
        if not lower <= parsed <= upper:
            raise argparse.ArgumentTypeError(
                f"{label} must be between {lower} and {upper}"
            )
        return parsed

    return parse


async def _run(args: argparse.Namespace) -> int:
    database = Database(get_settings().database_url)
    try:
        result = await wait_for_readiness(
            SqlAlchemyReadinessProbe(database.engine),
            attempts=args.attempts,
            attempt_timeout_seconds=args.attempt_timeout,
            delay_seconds=args.delay,
        )
        print(f"database readiness: ready after {result.attempts} attempt(s)")
        return 0
    finally:
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except Exception:
        print("database readiness failed within the retry budget", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
