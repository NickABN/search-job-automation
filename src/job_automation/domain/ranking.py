"""Deterministic, explainable job classification and ranking policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RoleFamily(StrEnum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    FULL_STACK = "full_stack"
    MOBILE = "mobile"
    DATA_AI = "data_ai"
    OTHER = "other"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"
    MANAGER = "manager"
    DIRECTOR = "director"
    UNKNOWN = "unknown"


class WorkModel(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


ROLE_MAX = {
    "role": 25,
    "skills": 25,
    "geography": 20,
    "experience": 10,
    "compensation": 10,
    "english": 5,
    "recency": 5,
}
DATA_AI_SECONDARY_POINTS = 10
_SUPPORTED_ENGLISH_LEVELS = frozenset(("B1", "B2", "C1", "C2", "NATIVE"))
_ENGLISH_ORDER = {"B1": 0, "B2": 1, "C1": 2, "C2": 3, "NATIVE": 4}
_ALIASES: dict[RoleFamily, tuple[str, ...]] = {
    RoleFamily.BACKEND: ("backend", "back end", "api engineer", "server-side"),
    RoleFamily.FRONTEND: ("frontend", "front end", "ui engineer", "web frontend"),
    RoleFamily.FULL_STACK: ("full stack", "full-stack", "fullstack"),
    RoleFamily.MOBILE: ("mobile", "android", "ios", "flutter", "react native"),
    RoleFamily.DATA_AI: (
        "data engineer",
        "data scientist",
        "machine learning",
        "ml engineer",
        "artificial intelligence",
    ),
}
_SKILLS = (
    "python",
    "fastapi",
    "java",
    "spring boot",
    "flutter",
    "react",
    "vue",
    "javascript",
    "typescript",
    "sql",
    "postgresql",
)
_MEXICO_CITIES = ("morelia", "guadalajara", "queretaro", "querétaro")


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")


def _require_optional_aware(value: datetime | None, field: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RankingProfile:
    identifier: str = "default-mexico-profile"
    version: str = "1"
    role_families: tuple[RoleFamily, ...] = (
        RoleFamily.BACKEND,
        RoleFamily.FRONTEND,
        RoleFamily.FULL_STACK,
        RoleFamily.MOBILE,
    )
    skills: tuple[str, ...] = (
        "python",
        "fastapi",
        "java",
        "spring boot",
        "flutter",
        "react",
        "vue",
    )
    target_monthly_mxn: int = 26000
    english_level: str = "B2"
    allowed_onsite_hybrid_cities: tuple[str, ...] = _MEXICO_CITIES

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        version = self.version.strip()
        if not identifier or not version:
            raise ValueError("ranking profile identifier and version must not be blank")
        if self.target_monthly_mxn <= 0:
            raise ValueError("ranking salary target must be positive")
        try:
            roles = tuple(
                value if isinstance(value, RoleFamily) else RoleFamily(value)
                for value in self.role_families
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "ranking profile contains an unsupported role family"
            ) from error
        if not roles:
            raise ValueError("ranking profile must include a target role family")
        skills = tuple(skill.strip().casefold() for skill in self.skills)
        cities = tuple(
            city.strip().casefold() for city in self.allowed_onsite_hybrid_cities
        )
        if not skills or any(not skill for skill in skills):
            raise ValueError("ranking profile must include nonblank target skills")
        if not cities or any(not city for city in cities):
            raise ValueError("ranking profile must include nonblank allowed cities")
        english_level = self.english_level.strip().upper()
        if english_level not in _SUPPORTED_ENGLISH_LEVELS:
            raise ValueError("ranking profile contains an unsupported English level")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "role_families", roles)
        object.__setattr__(self, "skills", skills)
        object.__setattr__(self, "english_level", english_level)
        object.__setattr__(self, "allowed_onsite_hybrid_cities", cities)


@dataclass(frozen=True, slots=True)
class JobListing:
    id: str
    title: str
    company: str
    description: str
    location_text: str | None
    published_at: datetime | None
    source_updated_at: datetime | None

    def __post_init__(self) -> None:
        for field in ("id", "title", "company"):
            _require_text(getattr(self, field), field)
        _require_optional_aware(self.published_at, "published_at")
        _require_optional_aware(self.source_updated_at, "source_updated_at")


@dataclass(frozen=True, slots=True)
class SalaryEvidence:
    minimum_monthly_mxn: int | None
    maximum_monthly_mxn: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class JobClassification:
    role_family: RoleFamily
    seniority: Seniority
    work_model: WorkModel
    matched_skills: tuple[str, ...]
    years_required: int | None
    english_requirement: str | None
    salary: SalaryEvidence


@dataclass(frozen=True, slots=True)
class FactorScore:
    name: str
    points: int
    maximum: int
    reason: str

    def __post_init__(self) -> None:
        if not 0 <= self.points <= self.maximum:
            raise ValueError("factor points must be within its maximum")


@dataclass(frozen=True, slots=True)
class RankingEvaluation:
    eligible: bool
    score: int
    classification: JobClassification
    factors: tuple[FactorScore, ...]
    explanations: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]
    evaluated_at: datetime
    policy_version: str
    profile_identifier: str

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if (
            not 0 <= self.score <= 100
            or sum(f.points for f in self.factors) != self.score
        ):
            raise ValueError("score must be 0..100 and equal factor points")
        if sum(f.maximum for f in self.factors) != 100:
            raise ValueError("factor maxima must sum to 100")


def _text(job: JobListing) -> str:
    return f"{job.title} {job.description}".casefold()


def _title_role(title: str) -> RoleFamily:
    # Aliases are ordered by title intent, not description frequency.
    for candidate in (
        RoleFamily.FULL_STACK,
        RoleFamily.MOBILE,
        RoleFamily.BACKEND,
        RoleFamily.FRONTEND,
        RoleFamily.DATA_AI,
    ):
        if any(_has_phrase(title, alias) for alias in _ALIASES[candidate]):
            return candidate
    return RoleFamily.OTHER


def _is_generic_software_title(title: str) -> bool:
    return any(
        _has_phrase(title, phrase)
        for phrase in (
            "software engineer",
            "software developer",
            "application developer",
        )
    )


def _description_role(description: str) -> RoleFamily:
    backend = (
        _has_phrase(description, "fastapi")
        or _has_phrase(description, "spring boot")
        or (
            any(_has_phrase(description, skill) for skill in ("java", "python"))
            and any(
                _has_phrase(description, signal)
                for signal in (
                    "backend",
                    "back end",
                    "api",
                    "server-side",
                    "server side",
                )
            )
        )
    )
    frontend = any(
        _has_phrase(description, skill) for skill in ("react", "vue")
    ) and any(
        _has_phrase(description, signal)
        for signal in ("frontend", "front end", "ui", "user interface", "web")
    )
    if backend and frontend:
        return RoleFamily.FULL_STACK
    if any(
        _has_phrase(description, signal)
        for signal in ("mobile", "flutter", "react native", "android", "ios")
    ):
        return RoleFamily.MOBILE
    if backend:
        return RoleFamily.BACKEND
    if frontend:
        return RoleFamily.FRONTEND
    if any(
        _has_phrase(description, signal)
        for signal in (
            "data engineer",
            "data scientist",
            "machine learning",
            "ml engineer",
            "artificial intelligence",
            "data pipeline",
        )
    ):
        return RoleFamily.DATA_AI
    return RoleFamily.OTHER


def _has_phrase(text: str, phrase: str) -> bool:
    return bool(
        re.search(
            r"(?<![a-z0-9])" + re.escape(phrase.casefold()) + r"(?![a-z0-9])", text
        )
    )


def classify(job: JobListing) -> JobClassification:
    text = _text(job)
    title = job.title.casefold()
    role = _title_role(title)
    if role is RoleFamily.OTHER and _is_generic_software_title(title):
        role = _description_role(job.description.casefold())
    if any(_has_phrase(title, x) for x in ("staff", "principal")):
        seniority = (
            Seniority.STAFF if _has_phrase(title, "staff") else Seniority.PRINCIPAL
        )
    elif any(_has_phrase(title, x) for x in ("director", "manager")):
        seniority = (
            Seniority.DIRECTOR if _has_phrase(title, "director") else Seniority.MANAGER
        )
    elif any(_has_phrase(title, x) for x in ("intern", "internship", "trainee")):
        seniority = Seniority.INTERN
    elif _has_phrase(title, "senior") or _has_phrase(title, "sr"):
        seniority = Seniority.SENIOR
    elif any(_has_phrase(title, x) for x in ("junior", "jr", "entry level")):
        seniority = Seniority.JUNIOR
    elif _has_phrase(title, "mid-level") or _has_phrase(title, "mid level"):
        seniority = Seniority.MID
    else:
        seniority = Seniority.UNKNOWN
    matched = tuple(skill for skill in _SKILLS if _has_phrase(text, skill))
    years_match = re.search(r"(\d+)\s*(?:-|to|–)\s*\d+\s+years?", text)
    if years_match is None:
        years_match = re.search(
            r"(?:at least|minimum(?: of)?|more than|over)\s*(\d+)\+?\s+years?",
            text,
        )
    if years_match is None:
        years_match = re.search(r"(\d+)\+?\s+years?", text)
    years = int(years_match.group(1)) if years_match else None
    english_match = re.search(
        r"(?:native\s+english|english\s+native|"
        r"(?:b1|b2|c1|c2)\s+english|english\s+(?:b1|b2|c1|c2))",
        text,
    )
    english = None
    if english_match:
        english_text = english_match.group(0)
        if "native" in english_text:
            english = "native"
        else:
            level_match = re.search(r"b1|b2|c1|c2", english_text)
            english = level_match.group(0) if level_match else None
    location = (job.location_text or "").casefold()
    work_text = f"{location} {job.description.casefold()}"
    work = (
        WorkModel.REMOTE
        if _has_phrase(work_text, "remote")
        else WorkModel.HYBRID
        if _has_phrase(work_text, "hybrid")
        else WorkModel.ONSITE
        if any(
            _has_phrase(work_text, phrase)
            for phrase in ("onsite", "on-site", "in office")
        )
        else WorkModel.UNKNOWN
    )
    return JobClassification(
        role, seniority, work, matched, years, english, _salary(text)
    )


def _salary(text: str) -> SalaryEvidence:
    period = (
        r"(?:per\s+month|monthly|a\s+month|/\s*month|per\s+year|"
        r"annual|annually|a\s+year|/\s*year)"
    )
    pattern = re.compile(
        r"(?:mxn|mx\$|mexican\s+pesos?)\s*\$?\s*([\d,.]+\s*k?|\$?[\d,.]+)\s*(?:-|to|–)\s*([\d,.]+\s*k?|\$?[\d,.]+)?\s*"
        + period
        + r"|(?:\$?[\d,.]+\s*k?)\s*(?:-|to|–)\s*(?:\$?[\d,.]+\s*k?)?\s*"
        + period
        + r"\s*(?:mxn|mx\$|mexican\s+pesos?)|"
        + r"(?:mxn|mx\$|mexican\s+pesos?)\s*\$?\s*([\d,.]+\s*k?|\$?[\d,.]+)\s*"
        + period,
        re.I,
    )
    match = pattern.search(text)
    if not match:
        return SalaryEvidence(
            None, None, "Salary is unknown or uses a deferred currency conversion."
        )
    numbers = re.findall(r"\d[\d,.]*\s*k?", match.group(0), re.I)
    values = []
    for number in numbers[:2]:
        value = number.lower().replace(",", "").strip()
        values.append(
            int(float(value[:-1]) * 1000) if value.endswith("k") else int(float(value))
        )
    annual = any(x in match.group(0).casefold() for x in ("year", "annual"))
    if annual:
        values = [round(value / 12) for value in values]
    return SalaryEvidence(
        values[0] if values else None,
        values[-1] if values else None,
        "Explicit MXN salary normalized to monthly."
        + (" Annual amount divided by 12." if annual else ""),
    )


