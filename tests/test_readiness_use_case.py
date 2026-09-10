import pytest

from job_automation.application.readiness import CheckReadiness


class Probe:
    def __init__(self) -> None:
        self.called = False

    async def check(self) -> None:
        self.called = True


@pytest.mark.asyncio
async def test_check_readiness_delegates_to_port() -> None:
    probe = Probe()
    await CheckReadiness(probe).execute()
    assert probe.called
