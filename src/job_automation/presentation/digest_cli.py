"""Manual, safe digest preparation and delivery command."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from job_automation.application.digests import DigestUnitOfWork, PrepareDigest
from job_automation.application.notifications import DeliverDigest
from job_automation.config import get_settings
from job_automation.domain.digests import DigestSlot
from job_automation.domain.jobs import utc_now
from job_automation.infrastructure.database import Database
from job_automation.infrastructure.delivery import SqlAlchemyDeliveryUnitOfWork
from job_automation.infrastructure.digests import SqlAlchemyDigestUnitOfWork
from job_automation.infrastructure.telegram import TelegramGateway, render_digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and send one job digest")
    parser.add_argument(
        "--slot", choices=[slot.value for slot in DigestSlot], required=True
    )
    parser.add_argument(
        "--date", type=date.fromisoformat, default=None, help="Local ISO date"
    )
    parser.add_argument("--min-score", type=int, default=None)
    parser.add_argument("--max-jobs", type=int, default=None)
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    timezone = ZoneInfo(settings.digest_timezone)
    now = datetime.now(timezone)
    local_date = args.date or now.date()
    slot = DigestSlot(args.slot)
    database = Database(settings.database_url)
    gateway = TelegramGateway(settings.telegram_bot_token, settings.telegram_chat_id)
    try:
        digest = await PrepareDigest(
            lambda: cast(
                DigestUnitOfWork,
                SqlAlchemyDigestUnitOfWork(database.session_factory()),
            ),
            timezone,
            settings.digest_min_score if args.min_score is None else args.min_score,
            settings.digest_max_jobs if args.max_jobs is None else args.max_jobs,
        ).execute(local_date, slot, now.astimezone())
        async with SqlAlchemyDeliveryUnitOfWork(database.session_factory()) as work:
            result = await DeliverDigest(
                work.delivery, gateway, utc_now, render_digest
            ).execute(digest)
        print(
            f"digest status={result.value} slot={slot.value} "
            f"date={local_date.isoformat()} items={len(digest.items)}"
        )
        return 0 if result.value == "sent" else 2
    finally:
        await gateway.aclose()
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except Exception:
        print("job digest delivery failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
