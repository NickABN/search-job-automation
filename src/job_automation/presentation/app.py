from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Response, status

from job_automation.application.ports import ReadinessProbe
from job_automation.application.readiness import CheckReadiness
from job_automation.config import Settings, get_settings
from job_automation.infrastructure.database import Database, SqlAlchemyReadinessProbe


def create_app(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    database = (
        None if readiness_probe is not None else Database(app_settings.database_url)
    )
    probe = readiness_probe or SqlAlchemyReadinessProbe(database.engine)  # type: ignore[union-attr]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if database is not None:
            await database.dispose()

    app = FastAPI(title="Search Job Automation", lifespan=lifespan)
    app.state.readiness = CheckReadiness(probe)

    def readiness_use_case() -> CheckReadiness:
        return cast(CheckReadiness, app.state.readiness)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(
        response: Response,
        use_case: Annotated[CheckReadiness, Depends(readiness_use_case)],
    ) -> dict[str, str]:
        try:
            await use_case.execute()
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unavailable"}
        return {"status": "ready"}

    return app
