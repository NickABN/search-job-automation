import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from job_automation.infrastructure.greenhouse import (
    GreenhouseError,
    GreenhouseJobSource,
)

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse_jobs.json"


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


@pytest.mark.asyncio
async def test_greenhouse_normalizes_content_and_preserves_raw_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=load_fixture())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = GreenhouseJobSource("acme-board", "Acme Inc", client=client)
    try:
        jobs = await source.fetch(datetime(2026, 1, 3, tzinfo=UTC))
    finally:
        await client.aclose()
    job = jobs[0]
    assert job.observation.source_job_id == "123"
    assert job.observation.description == "Build & ship. Line\ntwo"
    assert job.observation.source_updated_at == datetime(
        2026, 1, 2, 3, 4, 5, tzinfo=UTC
    )
    assert job.observation.published_at is None
    assert job.raw_payload["id"] == 123
    assert requests[0].url.params["content"] == "true"
    assert requests[0].url.path.endswith("/v1/boards/acme-board/jobs")


@pytest.mark.asyncio
async def test_greenhouse_board_identity_is_part_of_observation_identity() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json=load_fixture())
    )
    first_client = httpx.AsyncClient(transport=transport)
    second_client = httpx.AsyncClient(transport=transport)
    first = GreenhouseJobSource("first-board", "Acme", client=first_client)
    second = GreenhouseJobSource("second-board", "Other", client=second_client)
    try:
        first_job = (await first.fetch(datetime(2026, 1, 3, tzinfo=UTC)))[0]
        second_job = (await second.fetch(datetime(2026, 1, 3, tzinfo=UTC)))[0]
    finally:
        await first_client.aclose()
        await second_client.aclose()
    assert first.source_identity == "greenhouse:first-board"
    assert second.source_identity == "greenhouse:second-board"
    assert first_job.observation.source != second_job.observation.source
    assert first_job.observation.source_job_id == second_job.observation.source_job_id


@pytest.mark.asyncio
async def test_greenhouse_retries_transient_failures_and_not_permanent_errors() -> None:
    statuses = iter([503, 429, 200])
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, headers={"Retry-After": "1"}, json=load_fixture())

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = GreenhouseJobSource("acme", "Acme", client=client, sleep=sleep)
    try:
        assert len(await source.fetch(datetime(2026, 1, 1, tzinfo=UTC))) == 1
    finally:
        await client.aclose()
    assert sleeps == [1.0, 1.0]

    permanent = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404, text="secret body"))
    )
    source = GreenhouseJobSource("safe", "Acme", client=permanent)
    try:
        with pytest.raises(GreenhouseError, match="HTTP 404") as error:
            await source.fetch(datetime(2026, 1, 1, tzinfo=UTC))
    finally:
        await permanent.aclose()
    assert "secret body" not in str(error.value)
    assert "safe" not in str(error.value)


@pytest.mark.asyncio
async def test_greenhouse_honors_zero_retry_after() -> None:
    statuses = iter([429, 200])
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            next(statuses), headers={"Retry-After": "0"}, json=load_fixture()
        )

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = GreenhouseJobSource("acme", "Acme", client=client, sleep=sleep)
    try:
        await source.fetch(datetime(2026, 1, 1, tzinfo=UTC))
    finally:
        await client.aclose()
    assert sleeps == [0.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "&lt;p&gt;Encoded &amp;amp; text&lt;/p&gt;",
        (
            "&amp;lt;p&amp;gt;Double encoded&lt;/p&gt;"
            "&amp;lt;script&amp;gt;secret&amp;lt;/script&amp;gt;"
        ),
    ],
)
async def test_greenhouse_decodes_encoded_markup_and_removes_scripts(
    content: str,
) -> None:
    payload = load_fixture()
    job = payload["jobs"][0]
    assert isinstance(job, dict)
    job["content"] = content
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    source = GreenhouseJobSource("acme", "Acme", client=client)
    try:
        result = (await source.fetch(datetime(2026, 1, 1, tzinfo=UTC)))[0]
    finally:
        await client.aclose()
    assert (
        "Encoded & text" in result.observation.description
        or "Double encoded" in result.observation.description
    )
    assert "<p>" not in result.observation.description
    assert "secret" not in result.observation.description


@pytest.mark.asyncio
async def test_greenhouse_rejects_malformed_payload_without_leaking_body() -> None:
    body = {"jobs": [{"id": 1, "title": "missing fields", "content": "secret"}]}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    source = GreenhouseJobSource("safe", "Acme", client=client)
    try:
        with pytest.raises(GreenhouseError) as error:
            await source.fetch(datetime(2026, 1, 1, tzinfo=UTC))
    finally:
        await client.aclose()
    assert "secret" not in str(error.value)


def test_greenhouse_validates_board_token() -> None:
    with pytest.raises(ValueError):
        GreenhouseJobSource("bad/token", "Acme")
