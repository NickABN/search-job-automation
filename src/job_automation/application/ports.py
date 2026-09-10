from collections.abc import Awaitable
from typing import Protocol


class ReadinessProbe(Protocol):
    def check(self) -> Awaitable[None]:
        """Complete when the dependency is reachable, or raise on failure."""
