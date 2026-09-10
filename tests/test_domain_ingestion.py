from datetime import UTC, datetime

import pytest

from job_automation.domain.jobs import (
    IngestionRun,
    IngestionRunStatus,
    NormalizedJobObservation,
)


def observation(**overrides: object) -> NormalizedJobObservation:
    values: dict[str, object] = {
        "source": "example",
        "source_job_id": "42",
        "title": "Python Engineer",
        "company": "Acme",
        "description": "Build things",
        "canonical_url": "https://example.test/42",
        "source_url": None,
        "location_text": "Remote",
        "published_at": None,
        "source_updated_at": None,
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return NormalizedJobObservation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["source", "source_job_id", "title", "company"])
def test_observation_rejects_blank_required_text(field: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        observation(**{field: "  "})


def test_observation_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        observation(observed_at=datetime(2026, 1, 1))


def test_run_transitions_are_terminal_and_bound_error_size() -> None:
    started = IngestionRun.start("example", datetime(2026, 1, 1, tzinfo=UTC))
    finished = started.finish(
        datetime(2026, 1, 2, tzinfo=UTC), fetched=2, created=1, updated=1, unchanged=0
    )
    assert finished.status is IngestionRunStatus.SUCCEEDED
    with pytest.raises(ValueError, match="only running"):
        finished.fail(datetime(2026, 1, 3, tzinfo=UTC), "late")
    failed = started.fail(datetime(2026, 1, 2, tzinfo=UTC), "x" * 2000)
    assert failed.status is IngestionRunStatus.FAILED
    assert len(failed.error_summary or "") == 1000
