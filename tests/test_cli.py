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


@pytest.mark.asyncio
async def test_configured_cli_continues_after_one_board_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Database:
        def __init__(self, _: str) -> None:
            pass

        def session_factory(self) -> object:
            return object()

        async def dispose(self) -> None:
            pass

    class Source:
        def __init__(self, board_token: str, company: str) -> None:
            self.source_identity = f"greenhouse:{board_token}"
            self.company = company

        async def aclose(self) -> None:
            pass

    class UseCase:
        def __init__(self, **kwargs: object) -> None:
            self.source = kwargs["source"]

        async def execute(self) -> SimpleNamespace:
            if self.source.company == "Broken":
                raise RuntimeError("payload must not leak")
            return SimpleNamespace(
                status=SimpleNamespace(value="succeeded"),
                fetched_count=1,
                created_count=1,
                updated_count=0,
                unchanged_count=0,
            )

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(
        database_url="safe",
        greenhouse_boards=(
            SimpleNamespace(board_token="broken", company="Broken"),
            SimpleNamespace(board_token="good", company="Good"),
        ),
    ))
    monkeypatch.setattr(cli, "Database", Database)
    monkeypatch.setattr(cli, "GreenhouseJobSource", Source)
    monkeypatch.setattr(cli, "IngestJobs", UseCase)

    assert await cli._run(Namespace(board_token=None, company=None)) == 0
    output = capsys.readouterr()
    assert "Good: succeeded" in output.out
    assert "payload must not leak" not in output.out + output.err
