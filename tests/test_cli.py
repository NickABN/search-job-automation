from argparse import Namespace
from types import SimpleNamespace

import pytest

from job_automation.presentation import cli


def test_cli_help_does_not_expose_database_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])
    assert error.value.code == 0
    assert "--database-url" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_uses_settings_database_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Database:
        def __init__(self, url: str) -> None:
            assert url == "postgresql+asyncpg://safe-from-settings"

        def session_factory(self) -> object:
            return object()

        async def dispose(self) -> None:
            events.append("database-disposed")

    class Source:
        source_identity = "greenhouse:acme"

        def __init__(self, board_token: str, company: str) -> None:
            assert (board_token, company) == ("acme", "Acme")

        async def aclose(self) -> None:
            events.append("source-closed")

    class UseCase:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["source"].source_identity == "greenhouse:acme"
            assert kwargs["source_name"] == "greenhouse:acme"

        async def execute(self) -> SimpleNamespace:
            return SimpleNamespace(
                status=SimpleNamespace(value="succeeded"),
                fetched_count=1,
                created_count=1,
                updated_count=0,
                unchanged_count=0,
            )

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(
        database_url="postgresql+asyncpg://safe-from-settings"
    ))
    monkeypatch.setattr(cli, "Database", Database)
    monkeypatch.setattr(cli, "GreenhouseJobSource", Source)
    monkeypatch.setattr(cli, "IngestJobs", UseCase)

    result = await cli._run(Namespace(board_token="acme", company="Acme"))

    assert result == 0
    assert events == ["source-closed", "database-disposed"]
