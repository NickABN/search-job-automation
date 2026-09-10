from dataclasses import dataclass

from job_automation.application.ports import ReadinessProbe


@dataclass(frozen=True)
class CheckReadiness:
    probe: ReadinessProbe

    async def execute(self) -> None:
        await self.probe.check()
