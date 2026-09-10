"""Greenhouse Job Board API adapter."""

from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from job_automation.application.ingestion import FetchedJob, SourceError
from job_automation.domain.jobs import NormalizedJobObservation

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,190}$")
_MAX_RETRIES = 3
_MAX_RETRY_AFTER = 30.0


class GreenhouseError(SourceError):
    """A safe Greenhouse adapter error."""


def _clean_text(value: str) -> str:
    for _ in range(3):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    value = re.sub(
        r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise GreenhouseError(f"Greenhouse payload field {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GreenhouseError(f"Greenhouse payload field {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GreenhouseError(
            f"Greenhouse payload field {field} must include a timezone"
        )
    return parsed


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
        return max(0.0, min(seconds, _MAX_RETRY_AFTER))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            return max(
                0.0,
                min((target - datetime.now(UTC)).total_seconds(), _MAX_RETRY_AFTER),
            )
        except (TypeError, ValueError, OverflowError):
            return None


class GreenhouseJobSource:
    def __init__(
        self,
        board_token: str,
        company_name: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        base_url: str = "https://boards-api.greenhouse.io",
    ) -> None:
        if not _TOKEN_RE.fullmatch(board_token):
            raise ValueError("board_token must be a safe Greenhouse board identifier")
        if not company_name.strip():
            raise ValueError("company_name must not be blank")
        self.board_token = board_token
        self.company_name = company_name.strip()
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._sleep = sleep
        self._source_identity = f"greenhouse:{board_token}"
        self._url = (
            f"{base_url.rstrip('/')}/v1/boards/{quote(board_token, safe='')}/jobs"
        )

    @property
    def source_identity(self) -> str:
        return self._source_identity

    async def __aenter__(self) -> GreenhouseJobSource:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(self, observed_at: datetime) -> Sequence[FetchedJob]:
        response = await self._request()
        try:
            payload = response.json()
        except ValueError as exc:
            raise GreenhouseError("Greenhouse returned invalid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise GreenhouseError("Greenhouse payload has an invalid jobs list")
        result: list[FetchedJob] = []
        for raw in payload["jobs"]:
            if not isinstance(raw, dict):
                raise GreenhouseError("Greenhouse payload contains an invalid job")
            result.append(self._parse_job(raw, observed_at))
        return result

    async def _request(self) -> httpx.Response:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._client.get(self._url, params={"content": "true"})
            except httpx.TransportError as exc:
                if attempt == _MAX_RETRIES:
                    raise GreenhouseError(
                        "Greenhouse transport request failed"
                    ) from exc
                await self._sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == _MAX_RETRIES:
                    raise GreenhouseError(
                        "Greenhouse service request failed after retries"
                    )
                retry_after = _retry_after(response)
                await self._sleep(
                    retry_after if retry_after is not None else 2**attempt
                )
                continue
            if response.is_error:
                raise GreenhouseError(
                    f"Greenhouse request returned HTTP {response.status_code}"
                )
            return response
        raise AssertionError("retry loop must return or raise")

    def _parse_job(self, raw: dict[str, Any], observed_at: datetime) -> FetchedJob:
        try:
            raw_id = raw["id"]
            if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
                raise TypeError
            source_job_id = str(raw_id).strip()
            title = raw["title"]
            canonical_url = raw["absolute_url"]
            updated_at = _timestamp(raw["updated_at"], "updated_at")
            location = raw.get("location")
            location_text = location.get("name") if isinstance(location, dict) else None
            content = raw["content"]
            if not all(
                isinstance(value, str) for value in (title, canonical_url, content)
            ):
                raise TypeError
            if location_text is not None and not isinstance(location_text, str):
                raise TypeError
            if not source_job_id or not title.strip() or not content.strip():
                raise ValueError
            observation = NormalizedJobObservation(
                source=self.source_identity,
                source_job_id=source_job_id,
                title=title.strip(),
                company=self.company_name,
                description=_clean_text(content),
                canonical_url=canonical_url.strip(),
                source_url=canonical_url.strip(),
                location_text=location_text.strip() if location_text else None,
                published_at=None,
                source_updated_at=updated_at,
                observed_at=observed_at,
            )
        except (KeyError, TypeError, ValueError):
            raise GreenhouseError(
                "Greenhouse payload contains an invalid job"
            ) from None
        return FetchedJob(observation=observation, raw_payload=raw)
