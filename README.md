# Search Job Automation

This repository contains a production-shaped FastAPI service with framework-
independent ingestion, deterministic explainable ranking, and resumable job
digests. It stores normalized source observations, current evaluations, and
immutable digest snapshots safely and idempotently.

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
docker compose up -d db
docker compose build app
docker compose run --rm app alembic upgrade head
docker compose up -d app
```

Check `GET /health` for liveness and `GET /ready` for PostgreSQL readiness.
Stop local services with `docker compose down`.

## Architecture boundaries

| Boundary | Responsibility |
| --- | --- |
| `domain` | Immutable normalized-job and ingestion-run concepts with invariants |
| `application` | Cohesive use cases and dependency-inverting ports; no framework or database code |
| `infrastructure` | SQLAlchemy async mappings, transaction-owning unit of work, and readiness adapter |
| `presentation` | FastAPI composition root and HTTP endpoints |

The application factory is the composition root. Tests inject a fake readiness
port, while production composes the SQLAlchemy adapter and disposes the engine
through FastAPI lifespan shutdown.

## Commands

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
.venv\Scripts\python.exe -m pytest
docker compose config
docker compose --profile test run --rm integration-tests
```

From a clean database volume, that exact command waits for healthy PostgreSQL,
applies `alembic upgrade head`, and then runs all PostgreSQL integration tests.
The integration harness runs inside the Compose network. This is intentional:
Windows-host asyncpg connections to the published PostgreSQL port are not a
reliable verification path in this environment.

## Data model

`sources` identifies an adapter without storing credentials. `jobs` has one
row per `(source, source_job_id)`. `job_observations` preserves each changed
normalized payload as JSONB and uses `(job_id, content_hash)` for conservative
idempotency; repeated observations update `last_seen_at`. `ingestion_runs`
tracks lifecycle and bounded counters/errors. Alembic owns all schema changes;
the application never calls `create_all()`.

## Environment configuration

Copy `.env.example` to `.env`, then set `DATABASE_URL` to an
`postgresql+asyncpg` URL. Compose supplies the same setting to the app using
its PostgreSQL service. Ranking profile values use Pydantic JSON arrays for
role families, skills, and allowed onsite/hybrid cities:

```dotenv
RANKING_TARGET_ROLE_FAMILIES=["backend","frontend","full_stack","mobile"]
RANKING_TARGET_SKILLS=["Python","FastAPI","Java","Spring Boot","Flutter","React","Vue"]
RANKING_ENGLISH_LEVEL=B2
RANKING_ALLOWED_CITIES=["Morelia","Guadalajara","Queretaro"]
```

Never commit `.env` or real credentials. Profile values are validated before
ranking; skills and city names are normalized case-insensitively.

## Manual Greenhouse ingestion

After the database is running and migrated, ingest one public board:

```powershell
.venv\Scripts\python.exe -m job_automation.presentation.cli --board-token greenhouse --company "Greenhouse"
```

`--board-token` is a validated Greenhouse board identifier, not a secret. The
company name is explicit configuration because the listing API does not provide
a reliable company field. The adapter calls the official public endpoint once
with `content=true`, preserves each raw job JSON object, and leaves publication
time unknown. See the [official Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html).

## Job digests

A digest is keyed by `{local_date}:{slot}` (`morning` or `evening`) in the
configured `America/Mexico_City` timezone. Preparation runs at most once for a
key, selects current eligible evaluations at or above `DIGEST_MIN_SCORE` (60 by
default), orders ties deterministically, and stores job fields and reasons as an
immutable snapshot. Empty digests are persisted as explicit no-ops. Prepared,
sending, and sent items are excluded from later slots, so retries resume work
without claiming a job twice.

The 09:00/18:00 scheduler and Telegram transport are intentionally deferred to
the notification branch. Before a scheduler exists, delivery is explicit:
`.venv\\Scripts\\send-job-digest.exe --slot morning`. Telegram uses the
official Bot API `sendMessage` endpoint and environment-only credentials. Never
share or commit the bot token. Delivery is resumable for confirmed sent parts,
but a post-dispatch timeout is deliberately marked uncertain: Telegram offers
no caller idempotency key, so the command does not claim exactly-once delivery.
All operational timestamps are UTC-aware; the local date and slot remain
explicit database columns.

## Current non-goals

## Ranking jobs

After ingestion and migration, rank persisted jobs without network access:

```powershell
.venv\Scripts\rank-jobs.exe --limit 20
```

The limit is bounded to 1--1000. Output contains only score, title, company,
location, and concise stable reasons.

| Factor | Maximum |
| --- | ---: |
| Role-family match | 25 |
| Skills/stack match | 25 |
| Geographic/work-model fit | 20 |
| Experience/seniority fit | 10 |
| Compensation | 10 |
| English requirement | 5 |
| Recency | 5 |

Data/AI is a secondary affinity: when it is not a configured primary role, it
receives partial role credit rather than the full 25 points. English scoring is
relative to the configured candidate CEFR level; C1 is penalized for a B2
candidate, while native/C2 requirements remain hard exclusions.

Salary is normalized only for explicit MXN monthly or annual evidence; foreign
currencies and bare-dollar values remain neutral until a reviewed conversion
provider is added. Unknown location, salary, English, and recency are not hard
exclusions. No LLM, embeddings, vector database, scheduler, Telegram,
automatic applications, currency-rate provider, or frontend is included.

This work unit does not include Lever or cross-source fuzzy deduplication.
