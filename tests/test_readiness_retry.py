import pytest

from job_automation.application.readiness import (
    MAX_ATTEMPT_TIMEOUT_SECONDS,
    MAX_ATTEMPTS,
    MAX_DELAY_SECONDS,
    MIN_ATTEMPT_TIMEOUT_SECONDS,
    MIN_ATTEMPTS,
    MIN_DELAY_SECONDS,
    wait_for_readiness,
)


class EventuallyReadyProbe:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def check(self) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporarily unavailable")


class ReadyProbe:
    async def check(self) -> None:
        return None


@pytest.mark.asyncio
async def test_readiness_retries_then_succeeds_without_real_sleep() -> None:
    probe = EventuallyReadyProbe(failures=2)
    delays: list[float] = []

    async def no_sleep(delay: float) -> None:
        delays.append(delay)

    result = await wait_for_readiness(probe, delay_seconds=2, sleep=no_sleep)

    assert result.attempts == 3
    assert probe.calls == 3
    assert delays == [2, 2]


@pytest.mark.asyncio
async def test_readiness_failure_is_bounded_and_hides_provider_error() -> None:
    probe = EventuallyReadyProbe(failures=10)

    with pytest.raises(RuntimeError, match="retry budget"):
        await wait_for_readiness(probe, attempts=3, delay_seconds=0)

    assert probe.calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attempts", "attempt_timeout_seconds", "delay_seconds"),
    [
        (MIN_ATTEMPTS, MIN_ATTEMPT_TIMEOUT_SECONDS, MIN_DELAY_SECONDS),
        (MAX_ATTEMPTS, MAX_ATTEMPT_TIMEOUT_SECONDS, MAX_DELAY_SECONDS),
    ],
)
async def test_readiness_accepts_each_configured_boundary(
    attempts: int, attempt_timeout_seconds: float, delay_seconds: float
) -> None:
    result = await wait_for_readiness(
        ReadyProbe(), attempts=attempts,
        attempt_timeout_seconds=attempt_timeout_seconds,
        delay_seconds=delay_seconds,
    )

    assert result.attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attempts", "attempt_timeout_seconds", "delay_seconds"),
    [
        (MAX_ATTEMPTS + 1, 5.0, 2.0),
        (6, MAX_ATTEMPT_TIMEOUT_SECONDS + 0.1, 2.0),
        (6, 5.0, MAX_DELAY_SECONDS + 0.1),
    ],
)
async def test_readiness_rejects_values_over_each_configured_boundary(
    attempts: int, attempt_timeout_seconds: float, delay_seconds: float
) -> None:
    with pytest.raises(ValueError, match="readiness retry budget"):
        await wait_for_readiness(
            ReadyProbe(), attempts=attempts,
            attempt_timeout_seconds=attempt_timeout_seconds,
            delay_seconds=delay_seconds,
        )
