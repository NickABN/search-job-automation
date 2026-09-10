from datetime import UTC, datetime

import pytest

from job_automation.application.ranking import RankJobs
from job_automation.domain.ranking import (
    JobListing,
    RankingPolicy,
    RankingProfile,
    RoleFamily,
    classify,
)

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def job(
    title: str, description: str = "", location: str | None = "Remote Mexico"
) -> JobListing:
    return JobListing("id-1", title, "Acme", description, location, NOW, None)


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Java Backend Engineer", RoleFamily.BACKEND),
        ("JavaScript Frontend Engineer", RoleFamily.FRONTEND),
        ("Flutter Mobile Developer", RoleFamily.MOBILE),
    ],
)
def test_classification_uses_phrase_aliases(title: str, family: RoleFamily) -> None:
    assert classify(job(title)).role_family is family


def test_java_does_not_match_javascript() -> None:
    assert (
        "java"
        not in classify(job("Frontend Engineer", "JavaScript and React")).matched_skills
    )


def test_react_native_is_not_native_english() -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job("React Native Mobile Developer", "React Native and English B2"), NOW
    )
    assert evaluation.eligible
    assert evaluation.classification.english_requirement == "b2"


def test_native_and_c2_exclude_but_c1_is_eligible_with_penalty() -> None:
    policy = RankingPolicy(RankingProfile())
    native = policy.evaluate(job("Backend Engineer", "native English required"), NOW)
    c2 = policy.evaluate(job("Backend Engineer", "C2 English required"), NOW)
    c1 = policy.evaluate(job("Backend Engineer", "C1 English required"), NOW)
    b2 = policy.evaluate(job("Backend Engineer", "B2 English required"), NOW)
    assert not native.eligible and not c2.eligible
    assert c1.eligible and c1.score < b2.score


@pytest.mark.parametrize(
    "title",
    ["Manager Backend Engineer", "Staff Backend Engineer", "Intern Backend Engineer"],
)
def test_title_seniority_is_hard_excluded(title: str) -> None:
    assert not RankingPolicy(RankingProfile()).evaluate(job(title), NOW).eligible


def test_incidental_description_seniority_is_ignored() -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job(
            "Backend Engineer",
            "Work with product managers, mentor interns, and collaborate with "
            "principal engineers.",
        ),
        NOW,
    )
    assert evaluation.eligible
    assert evaluation.classification.seniority.value == "unknown"


def test_title_intent_precedes_mixed_description() -> None:
    assert (
        classify(
            job("Full Stack Engineer", "Backend APIs are mentioned before frontend UI.")
        ).role_family
        is RoleFamily.FULL_STACK
    )


@pytest.mark.parametrize(
    "title",
    [
        "Commercial Counsel",
        "Growth Account Executive",
        "Sales Development Representative",
        "Strategic Consultant",
    ],
)
def test_non_engineering_titles_do_not_inherit_description_technology(
    title: str,
) -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job(title, "Work with backend APIs, Python, React, and product teams."), NOW
    )
    assert evaluation.classification.role_family is RoleFamily.OTHER
    assert not evaluation.eligible


def test_generic_software_title_uses_coherent_backend_cluster() -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job("Software Engineer", "Build Python services with FastAPI."), NOW
    )
    assert evaluation.classification.role_family is RoleFamily.BACKEND
    assert evaluation.eligible


def test_generic_software_title_uses_coherent_full_stack_cluster() -> None:
    classification = classify(
        job(
            "Software Developer",
            "Build Python FastAPI APIs and React frontend applications.",
        )
    )
    assert classification.role_family is RoleFamily.FULL_STACK
    assert (
        classify(
            job(
                "React Native Mobile Developer",
                "Backend services and React are required.",
            )
        ).role_family
        is RoleFamily.MOBILE
    )


@pytest.mark.parametrize(
    ("location", "description", "eligible"),
    [
        ("Mexico", "Backend Engineer", True),
        ("LATAM", "Backend Engineer", True),
        ("Guadalajara", "On-site backend engineer", True),
        ("Morelia", "Hybrid backend engineer", True),
        ("Mexico City", "Onsite backend engineer", False),
        ("Remote - US only", "Backend engineer", False),
    ],
)
def test_location_ambiguity_and_restrictions(
    location: str, description: str, eligible: bool
) -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job("Backend Engineer", description, location), NOW
    )
    assert evaluation.eligible is eligible


@pytest.mark.parametrize(
    ("location", "eligible"),
    [
        ("Anywhere in the United States", False),
        ("Anywhere in Ireland", False),
        ("Anywhere in Mexico", True),
        ("Anywhere in Latin America", True),
        ("Anywhere in LATAM", True),
        ("Worldwide", True),
    ],
)
def test_anywhere_location_restrictions(location: str, eligible: bool) -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job("Backend Engineer", "Python", location), NOW
    )
    assert evaluation.eligible is eligible


def test_recognized_role_outside_primary_targets_is_excluded() -> None:
    profile = RankingProfile(role_families=(RoleFamily.BACKEND,))
    evaluation = RankingPolicy(profile).evaluate(job("Frontend Engineer", "React"), NOW)
    assert not evaluation.eligible
    assert evaluation.factors[0].points == 0


def test_data_ai_remains_secondary_affinity_when_not_primary() -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job("Data Scientist", "Python and machine learning"), NOW
    )
    assert evaluation.classification.role_family is RoleFamily.DATA_AI
    assert evaluation.factors[0].points == 10
    assert evaluation.eligible


@pytest.mark.parametrize(
    ("description", "years"),
    [
        ("2-6 years experience", 2),
        ("at least 6 years experience", 6),
        ("minimum 6 years experience", 6),
        ("more than 6 years experience", 6),
        ("6+ years experience", 6),
    ],
)
def test_years_uses_minimum_requirement(description: str, years: int) -> None:
    assert classify(job("Backend Engineer", description)).years_required == years


def test_specialized_skills_receive_full_tier_credit() -> None:
    policy = RankingPolicy(RankingProfile())
    no_skills = policy.evaluate(job("Backend Engineer", "General engineering"), NOW)
    one_skill = policy.evaluate(job("Backend Engineer", "Python"), NOW)
    two_skills = policy.evaluate(job("Backend Engineer", "Python FastAPI"), NOW)
    assert [
        factor.points
        for factor in (
            no_skills.factors[1],
            one_skill.factors[1],
            two_skills.factors[1],
        )
    ] == [0, 15, 25]


def test_future_published_at_is_not_recent() -> None:
    future = JobListing(
        "future",
        "Backend Engineer",
        "Acme",
        "Python",
        "Remote",
        NOW.replace(day=20),
        None,
    )
    evaluation = RankingPolicy(RankingProfile()).evaluate(future, NOW)
    assert evaluation.factors[-1].points == 0


@pytest.mark.parametrize("field", ["id", "title", "company"])
def test_job_listing_rejects_blank_identity_fields(field: str) -> None:
    values = {
        "id": "id-1",
        "title": "Backend Engineer",
        "company": "Acme",
        "description": "Python",
        "location_text": "Remote",
        "published_at": NOW,
        "source_updated_at": None,
    }
    values[field] = " "
    with pytest.raises(ValueError, match=f"{field} must not be blank"):
        JobListing(**values)


def test_job_listing_rejects_naive_optional_timestamps() -> None:
    with pytest.raises(ValueError, match="published_at must be timezone-aware"):
        JobListing(
            "id",
            "Backend Engineer",
            "Acme",
            "Python",
            None,
            datetime(2026, 1, 1),
            None,
        )


@pytest.mark.parametrize(
    ("description", "monthly"),
    [
        ("MXN 30,000 monthly", 30000),
        ("MXN 360k annual", 30000),
        ("MXN 25k-35k per month", 35000),
    ],
)
def test_conservative_mxn_salary(description: str, monthly: int) -> None:
    assert (
        classify(job("Backend Engineer", description)).salary.maximum_monthly_mxn
        == monthly
    )


def test_bare_dollar_and_foreign_currency_are_neutral() -> None:
    for description in ("$20,000 monthly", "USD 20,000 monthly"):
        assert (
            classify(job("Backend Engineer", description)).salary.maximum_monthly_mxn
            is None
        )


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Backend Intern", ""),
        ("Staff Backend Engineer", ""),
        ("Backend Engineer", "native English required"),
        ("Backend Engineer", "6+ years experience"),
    ],
)
def test_hard_exclusions(title: str, description: str) -> None:
    assert (
        not RankingPolicy(RankingProfile())
        .evaluate(job(title, description), NOW)
        .eligible
    )


def test_factor_invariants_and_stable_reasons() -> None:
    evaluation = RankingPolicy(RankingProfile()).evaluate(
        job("Backend Python Engineer", "Python FastAPI B2"), NOW
    )
    assert sum(f.points for f in evaluation.factors) == evaluation.score
    assert tuple(f.reason for f in evaluation.factors) == evaluation.explanations
    assert [f.maximum for f in evaluation.factors] == [25, 25, 20, 10, 10, 5, 5]


@pytest.mark.asyncio
async def test_application_saves_and_orders_top_eligible_results() -> None:
    class Work:
        def __init__(self) -> None:
            self.jobs = self
            self.evaluations = self
            self.saved: list[str] = []

        async def list_jobs(self) -> list[JobListing]:
            return [
                job("Backend Engineer"),
                JobListing(
                    "id-2",
                    "Backend Engineer",
                    "Acme",
                    "Python",
                    "Remote Mexico",
                    NOW,
                    None,
                ),
            ]

        async def save_evaluation(self, job_id: str, evaluation: object) -> None:
            self.saved.append(job_id)

        async def __aenter__(self) -> "Work":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    work = Work()
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return NOW

    results = await RankJobs(
        lambda: work, RankingPolicy(RankingProfile()), clock
    ).execute(1)
    assert len(results) == 1
    assert work.saved == ["id-1", "id-2"]
    assert clock_calls == 1
