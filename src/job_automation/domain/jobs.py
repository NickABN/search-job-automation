"""Normalized job observations and ingestion-run state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


def _require_text(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be blank")
    return value


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class NormalizedJobObservation:
    source: str
    source_job_id: str
    title: str
    company: str
    description: str
    canonical_url: str
    source_url: str | None
    location_text: str | None
    published_at: datetime | None
    source_updated_at: datetime | None
    observed_at: datetime

    def __post_init__(self) -> None:
        for field in ("source", "source_job_id", "title", "company", "canonical_url"):
            _require_text(getattr(self, field), field)
        _require_aware(self.observed_at, "observed_at")
        for field in ("published_at", "source_updated_at"):
            value = getattr(self, field)
            if value is not None:
                _require_aware(value, field)

    @property
    def content_hash(self) -> str:
        payload = {
            "title": " ".join(self.title.split()).casefold(),
            "company": " ".join(self.company.split()).casefold(),
            "description": " ".join(self.description.split()),
            "canonical_url": self.canonical_url.strip(),
            "source_url": self.source_url.strip() if self.source_url else None,
            "location_text": self.location_text.strip() if self.location_text else None,
            "published_at": self.published_at.isoformat()
            if self.published_at
            else None,
            "source_updated_at": self.source_updated_at.isoformat()
            if self.source_updated_at
            else None,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class IngestionRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestionRun:
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    status: IngestionRunStatus = IngestionRunStatus.RUNNING
    fetched_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    error_summary: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source, "source")
        _require_aware(self.started_at, "started_at")
        if self.finished_at is not None:
            _require_aware(self.finished_at, "finished_at")
        if any(
            value < 0
            for value in (
                self.fetched_count,
                self.created_count,
                self.updated_count,
                self.unchanged_count,
            )
        ):
            raise ValueError("ingestion counters must not be negative")
        if self.status is IngestionRunStatus.RUNNING and self.finished_at is not None:
            raise ValueError("running ingestion runs cannot have finished_at")
        if self.status is not IngestionRunStatus.RUNNING and self.finished_at is None:
            raise ValueError("finished ingestion runs require finished_at")
        if self.error_summary is not None and len(self.error_summary) > 1000:
            raise ValueError("error_summary must be at most 1000 characters")

    @classmethod
    def start(cls, source: str, started_at: datetime) -> IngestionRun:
        return cls(source=source, started_at=started_at)

    def finish(
        self,
        finished_at: datetime,
        *,
        fetched: int,
        created: int,
        updated: int,
        unchanged: int,
    ) -> IngestionRun:
        if self.status is not IngestionRunStatus.RUNNING:
            raise ValueError("only running ingestion runs can finish")
        return IngestionRun(
            self.source,
            self.started_at,
            finished_at,
            IngestionRunStatus.SUCCEEDED,
            fetched,
            created,
            updated,
            unchanged,
        )

    def fail(self, finished_at: datetime, error_summary: str) -> IngestionRun:
        if self.status is not IngestionRunStatus.RUNNING:
            raise ValueError("only running ingestion runs can fail")
        return IngestionRun(
            self.source,
            self.started_at,
            finished_at,
            IngestionRunStatus.FAILED,
            self.fetched_count,
            self.created_count,
            self.updated_count,
            self.unchanged_count,
            error_summary[:1000],
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
