from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_automation.domain.ranking import RankingProfile, RoleFamily


class GreenhouseBoard(BaseModel):
    """Public Greenhouse board configuration."""

    board_token: str
    company: str


DEFAULT_GREENHOUSE_BOARDS = (
    GreenhouseBoard(board_token="bitso", company="Bitso"),
    GreenhouseBoard(board_token="wizeline", company="Wizeline"),
    GreenhouseBoard(board_token="clara", company="Clara"),
    GreenhouseBoard(board_token="remotecom", company="Remote"),
    GreenhouseBoard(board_token="gitlab", company="GitLab"),
    GreenhouseBoard(board_token="airbnb", company="Airbnb"),
    GreenhouseBoard(board_token="ebanx", company="EBANX"),
)


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://app:app@127.0.0.1:5432/job_automation"
    ranking_profile_identifier: str = "default-mexico-profile"
    ranking_policy_version: str = "1"
    ranking_target_monthly_mxn: int = 26000
    ranking_limit: int = 20
    digest_min_score: int = 60
    digest_max_jobs: int = 20
    digest_timezone: str = "America/Mexico_City"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    greenhouse_boards: tuple[GreenhouseBoard, ...] = DEFAULT_GREENHOUSE_BOARDS
    ranking_target_role_families: tuple[str, ...] = (
        "backend",
        "full_stack",
        "mobile",
        "data_engineer",
        "data_analyst",
    )
    ranking_target_skills: tuple[str, ...] = (
        "Python",
        "FastAPI",
        "Java",
        "Spring Boot",
        "Flutter",
        "React",
        "Vue",
    )
    ranking_english_level: str = "B2"
    ranking_allowed_cities: tuple[str, ...] = (
        "Morelia",
        "Guadalajara",
        "Queretaro",
    )

    def ranking_profile(self) -> RankingProfile:
        try:
            role_families = tuple(
                RoleFamily(value) for value in self.ranking_target_role_families
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "ranking profile contains an unsupported role family"
            ) from error
        return RankingProfile(
            identifier=self.ranking_profile_identifier,
            version=self.ranking_policy_version,
            target_monthly_mxn=self.ranking_target_monthly_mxn,
            role_families=role_families,
            skills=self.ranking_target_skills,
            english_level=self.ranking_english_level,
            allowed_onsite_hybrid_cities=self.ranking_allowed_cities,
        )

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
