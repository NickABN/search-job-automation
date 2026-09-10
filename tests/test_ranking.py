from datetime import UTC, datetime

import pytest

from job_automation.domain.ranking import JobListing, RoleFamily, WorkModel, classify

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def job(
    title: str, description: str = "", location: str | None = "Remote Mexico"
) -> JobListing:
    return JobListing("id-1", title, "Acme", description, location, NOW, None)


@pytest.mark.parametrize(
    ("title", "family"),
    [("Java Backend Engineer", RoleFamily.BACKEND),
     ("JavaScript Frontend Engineer", RoleFamily.FRONTEND),
     ("Flutter Mobile Developer", RoleFamily.MOBILE)],
)
def test_title_aliases_are_authoritative(title: str, family: RoleFamily) -> None:
    assert classify(job(title)).role_family is family


def test_generic_software_title_uses_coherent_description_cluster() -> None:
    result = classify(job("Software Engineer", "Build Python services with FastAPI."))
    assert result.role_family is RoleFamily.BACKEND


def test_exact_skill_matching_avoids_java_in_javascript() -> None:
    result = classify(job("Frontend Engineer", "JavaScript and React"))
    assert "java" not in result.matched_skills


def test_classification_detects_seniority_work_model_and_english() -> None:
    result = classify(
        job("Senior Backend Engineer", "Python C1 English", "Hybrid Morelia")
    )
    assert result.seniority.value == "senior"
    assert result.work_model is WorkModel.HYBRID
    assert result.english_requirement == "c1"


@pytest.mark.parametrize(
    "location", ["Remote - US only", "Anywhere in the United States"]
)
def test_geography_restriction_signals_are_preserved(location: str) -> None:
    result = classify(job("Backend Engineer", "Python", location))
    assert result.work_model in (WorkModel.REMOTE, WorkModel.UNKNOWN)


@pytest.mark.parametrize("field", ["id", "title", "company"])
def test_listing_rejects_blank_identity(field: str) -> None:
    values = dict(
        id="id-1", title="Backend Engineer", company="Acme", description="Python",
        location_text="Remote", published_at=NOW, source_updated_at=None,
    )
    values[field] = " "
    with pytest.raises(ValueError):
        JobListing(**values)
