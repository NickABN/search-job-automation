"""Telegram Bot API adapter with bounded, safe HTML delivery."""

import asyncio
import hashlib
import html
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from job_automation.application.notifications import DeliveryError, DeliveryState
from job_automation.domain.digests import JobDigest

MAX_MESSAGE = 4096
SAFE_MESSAGE = 3900
_MAX_RETRY_AFTER = 30.0


def _text(value: str, limit: int = 500) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    try:
        return max(0.0, min(float(value), _MAX_RETRY_AFTER))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            return max(
                0.0,
                min(
                    (target - datetime.now(target.tzinfo)).total_seconds(),
                    _MAX_RETRY_AFTER,
                ),
            )
        except (TypeError, ValueError, OverflowError):
            return None


def _safe_url(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return value if len(value) <= 1000 else None


def _safe_url_text(value: str) -> str:
    parsed = urlsplit(value)
    display = value.split(":", 1)[1] if parsed.scheme else value
    return html.escape(_text(display, 200))


def render_digest(digest: JobDigest) -> Sequence[str]:
    header = (
        f"<b>Job digest: {html.escape(digest.slot.value)} · "
        f"{digest.local_date.isoformat()}</b>"
    )
    chunks: list[str] = []
    current = header
    for item in digest.items:
        reasons = "; ".join(_text(reason, 100) for reason in item.reasons[:3])
        safe_url = _safe_url(item.canonical_url)
        link = (
            f'<a href="{html.escape(safe_url, quote=True)}">Open job</a>'
            if safe_url is not None
            else _safe_url_text(item.canonical_url)
        )
        block = (
            f"\n\n<b>{html.escape(_text(item.title, 180))}</b> · {item.score}/100\n"
            f"{html.escape(_text(item.company, 100))} · "
            f"{html.escape(_text(item.role_family, 50))} · "
            f"{html.escape(_text(item.location, 80))}\n"
            f"{html.escape(reasons)}\n{link}"
        )
        if len(current) + len(block) > SAFE_MESSAGE and current != header:
            chunks.append(current)
            current = header + block
        else:
            current += block
    chunks.append(current)
    if any(len(part) > MAX_MESSAGE for part in chunks):
        raise AssertionError("bounded renderer produced an oversized part")
    return tuple(chunks)


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TelegramGateway:
    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not token.strip() or not chat_id.strip():
            raise ValueError("Telegram settings must not be blank")
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._sleep = sleep

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send(self, content: str) -> str:
        if len(content) > MAX_MESSAGE:
            raise DeliveryError(DeliveryState.PERMANENT_FAILED, "message_too_long")
        for attempt in range(4):
            try:
                response = await self._client.post(
                    self._url,
                    json={
                        "chat_id": self._chat_id,
                        "text": content,
                        "parse_mode": "HTML",
                    },
                )
            except (httpx.ConnectError, httpx.PoolTimeout) as error:
                if attempt == 3:
                    raise DeliveryError(
                        DeliveryState.PERMANENT_FAILED, "connect_failed"
                    ) from error
                await self._sleep(2**attempt)
                continue
            except (httpx.ReadTimeout, httpx.WriteTimeout) as error:
                raise DeliveryError(
                    DeliveryState.UNCERTAIN, "post_dispatch_timeout"
                ) from error
            try:
                data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
            except ValueError:
                data = {}
            if response.status_code == 429:
                if attempt == 3:
                    raise DeliveryError(
                        DeliveryState.PERMANENT_FAILED, "provider_retry_exhausted"
                    )
                retry_after = _retry_after(response)
                await self._sleep(2**attempt if retry_after is None else retry_after)
                continue
            if response.status_code >= 500:
                raise DeliveryError(DeliveryState.UNCERTAIN, "provider_5xx")
            if response.is_error or data.get("ok") is not True:
                raise DeliveryError(DeliveryState.PERMANENT_FAILED, "provider_rejected")
            message_id = data.get("result", {}).get("message_id")
            if message_id is None:
                raise DeliveryError(
                    DeliveryState.PERMANENT_FAILED, "provider_invalid_success"
                )
            return str(message_id)
        raise AssertionError("retry loop must return or raise")
