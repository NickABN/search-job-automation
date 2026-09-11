from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from job_automation.config import Settings
from job_automation.domain.ranking import JobListing, RankingPolicy, RoleFamily

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def job(title: str, description: str) -> JobListing:
    return JobListing(
        "config-job", title, "Acme", description, "Remote Mexico", NOW, None
    )


def test_settings_overrides_reach_domain_profile() -> None:
    settings = Settings(
        _env_file=None,
        ranking_profile_identifier="configured-profile",
        ranking_policy_version="configured-version",
        ranking_target_monthly_mxn=30000,
        ranking_target_role_families=("data_ai",),
        ranking_target_skills=("Python",),
        ranking_english_level="C1",
        ranking_allowed_cities=("Merida",),
    )

    profile = settings.ranking_profile()

    assert profile.identifier == "configured-profile"
    assert profile.version == "configured-version"
    assert profile.target_monthly_mxn == 30000
    assert profile.role_families == (RoleFamily.DATA_AI,)
    assert profile.skills == ("python",)
    assert profile.english_level == "C1"
    assert profile.allowed_onsite_hybrid_cities == ("merida",)


def test_default_digest_timezone_produces_aware_datetime() -> None:
    settings = Settings(_env_file=None)

    scheduled_at = datetime.now(ZoneInfo(settings.digest_timezone))

    assert settings.digest_timezone == "America/Mexico_City"
    assert scheduled_at.tzinfo is not None
    assert scheduled_at.utcoffset() is not None


def test_environment_profile_values_reach_domain_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RANKING_TARGET_ROLE_FAMILIES", '["frontend"]')
    monkeypatch.setenv("RANKING_TARGET_SKILLS", '["React"]')
    monkeypatch.setenv("RANKING_ENGLISH_LEVEL", "C1")
    monkeypatch.setenv("RANKING_ALLOWED_CITIES", '["Guadalajara"]')

    profile = Settings(_env_file=None).ranking_profile()

    assert profile.role_families == (RoleFamily.FRONTEND,)
    assert profile.skills == ("react",)
    assert profile.english_level == "C1"
    assert profile.allowed_onsite_hybrid_cities == ("guadalajara",)


def test_configured_profile_changes_english_points_and_skill_matching() -> None:
    b2 = Settings(
        _env_file=None, ranking_english_level="B2", ranking_target_skills=("Python",)
    ).ranking_profile()
    c1 = Settings(
        _env_file=None, ranking_english_level="C1", ranking_target_skills=("Python",)
    ).ranking_profile()
    b2_evaluation = RankingPolicy(b2).evaluate(
        job("Backend Engineer", "Python C1 English"), NOW
    )
    c1_evaluation = RankingPolicy(c1).evaluate(
        job("Backend Engineer", "Python C1 English"), NOW
    )

    assert b2_evaluation.factors[1].points == 15
    assert b2_evaluation.factors[5].points == 2
    assert c1_evaluation.factors[5].points == 5


def test_data_ai_is_secondary_when_not_a_primary_target() -> None:
    evaluation = RankingPolicy(Settings(_env_file=None).ranking_profile()).evaluate(
        job("Data Scientist", "Python and machine learning"), NOW
    )
    assert evaluation.classification.role_family is RoleFamily.DATA_AI
    assert evaluation.factors[0].points == 0
    assert not evaluation.eligible


def test_default_greenhouse_registry_and_target_roles() -> None:
    settings = Settings(_env_file=None)
    assert [
        (board.board_token, board.company) for board in settings.greenhouse_boards
    ] == [
        ("bitso", "Bitso"),
        ("wizeline", "Wizeline"),
        ("clara", "Clara"),
        ("remotecom", "Remote"),
        ("gitlab", "GitLab"),
        ("airbnb", "Airbnb"),
        ("ebanx", "EBANX"),
    ]
    assert settings.ranking_profile().role_families == (
        RoleFamily.BACKEND,
        RoleFamily.FULL_STACK,
        RoleFamily.MOBILE,
        RoleFamily.DATA_ENGINEER,
        RoleFamily.DATA_ANALYST,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"ranking_profile_identifier": " "},
        {"ranking_policy_version": " "},
        {"ranking_target_monthly_mxn": 0},
        {"ranking_target_role_families": ()},
        {"ranking_target_skills": ()},
        {"ranking_allowed_cities": ()},
        {"ranking_english_level": "A2"},
        {"ranking_target_role_families": ("unsupported",)},
    ],
)
def test_invalid_profile_configuration_is_rejected(
    overrides: dict[str, object],
) -> None:
    settings = Settings(_env_file=None, **overrides)
    with pytest.raises(ValueError):
        settings.ranking_profile()
