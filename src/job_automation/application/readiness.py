import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from job_automation.application.ports import ReadinessProbe

MIN_ATTEMPTS = 1
MAX_ATTEMPTS = 12
MIN_ATTEMPT_TIMEOUT_SECONDS = 0.1
MAX_ATTEMPT_TIMEOUT_SECONDS = 30.0
MIN_DELAY_SECONDS = 0.0
MAX_DELAY_SECONDS = 30.0


@dataclass(frozen=True)
class CheckReadiness:
    probe: ReadinessProbe

    async def execute(self) -> None:
        await self.probe.check()


@dataclass(frozen=True)
class ReadinessResult:
    attempts: int


async def wait_for_readiness(
    probe: ReadinessProbe,
    *,
    attempts: int = 6,
    attempt_timeout_seconds: float = 5.0,
    delay_seconds: float = 2.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ReadinessResult:
    """Wait for a dependency with bounded retries and per-attempt timeout."""
    if not MIN_ATTEMPTS <= attempts <= MAX_ATTEMPTS:
        raise ValueError("attempts must stay within the readiness retry budget")
    if not (
        MIN_ATTEMPT_TIMEOUT_SECONDS
        <= attempt_timeout_seconds
        <= MAX_ATTEMPT_TIMEOUT_SECONDS
    ):
        raise ValueError("attempt timeout must stay within the readiness retry budget")
    if not MIN_DELAY_SECONDS <= delay_seconds <= MAX_DELAY_SECONDS:
        raise ValueError("retry delay must stay within the readiness retry budget")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await asyncio.wait_for(probe.check(), timeout=attempt_timeout_seconds)
            return ReadinessResult(attempts=attempt)
        except Exception as error:
            last_error = error
            if attempt < attempts:
                await sleep(delay_seconds)
    raise RuntimeError(
        "database readiness did not succeed within the retry budget"
    ) from last_error
