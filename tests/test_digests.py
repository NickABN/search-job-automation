from datetime import UTC, date, datetime

import pytest

from job_automation.application.digests import PrepareDigest
from job_automation.domain.digests import (
    DigestItem,
    DigestSlot,
    DigestStatus,
    JobDigest,
)
from job_automation.presentation.digest_cli import _parser

AT = datetime(2026, 9, 10, 15, tzinfo=UTC)


def item(job_id: str = "job-1") -> DigestItem:
    return DigestItem(
        job_id,
        "Engineer",
        "Acme",
        "Remote",
        "https://example.test/1",
        80,
        "backend",
        ("Strong role match",),
    )


def test_digest_validates_invariants_and_transitions() -> None:
    digest = JobDigest(
        "d", date(2026, 9, 10), DigestSlot.MORNING, AT, DigestStatus.PREPARED, (item(),)
    )
    assert digest.idempotency_key == "2026-09-10:morning"
    assert digest.transition(DigestStatus.SENDING).status is DigestStatus.SENDING
    with pytest.raises(ValueError):
        digest.transition(DigestStatus.SENT)


def test_digest_slots_have_distinct_idempotency_keys() -> None:
    keys = {
        JobDigest(
            "d", date(2026, 9, 10), slot, AT, DigestStatus.EMPTY, ()
        ).idempotency_key
        for slot in DigestSlot
    }
    assert keys == {
        "2026-09-10:morning",
        "2026-09-10:midday",
        "2026-09-10:evening",
    }


def test_digest_cli_exposes_midday_slot() -> None:
    assert _parser().parse_args(["--slot", "midday"]).slot == "midday"


def test_empty_digest_is_explicit() -> None:
    empty = JobDigest(
        "d", date(2026, 9, 10), DigestSlot.EVENING, AT, DigestStatus.EMPTY, ()
    )
    assert empty.items == ()
    with pytest.raises(ValueError):
        JobDigest(
            "d",
            date(2026, 9, 10),
            DigestSlot.EVENING,
            AT,
            DigestStatus.EMPTY,
            (item(),),
        )


@pytest.mark.asyncio
async def test_prepare_validates_local_date_and_delegates() -> None:
    class Store:
        async def prepare(self, local_date, slot, scheduled_at, threshold, max_jobs):
            return JobDigest(
                "d", local_date, slot, scheduled_at, DigestStatus.EMPTY, ()
            )

    class Work:
        digests = Store()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    result = await PrepareDigest(
        lambda: Work(), UTC
    ).execute(date(2026, 9, 10), DigestSlot.MORNING, AT)
    assert result.status is DigestStatus.EMPTY
    with pytest.raises(ValueError, match="local_date"):
        await PrepareDigest(lambda: Work(), UTC).execute(
            date(2026, 9, 11), DigestSlot.MORNING, AT
        )
