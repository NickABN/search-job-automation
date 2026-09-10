# Engineering Standards

## Architecture

- Apply SOLID and Clean Architecture proportionally to the problem.
- Keep domain and application code independent of FastAPI, SQLAlchemy, and external services.
- Define narrow application ports and implement them at infrastructure boundaries.
- Keep transaction ownership explicit and preserve atomic use-case operations.
- Avoid speculative abstractions, empty layers, microservices, and framework coupling.

## Python

- Target Python 3.12 and use complete type annotations.
- Keep mypy strict mode and Ruff checks passing.
- Use timezone-aware datetimes and store operational timestamps in UTC.
- Never expose credentials, raw environment values, or sensitive payloads in logs or errors.

## Persistence

- Manage schema changes exclusively through Alembic migrations.
- Verify PostgreSQL-specific behavior against PostgreSQL, not SQLite substitutes.
- Preserve idempotency and database constraints at concurrency boundaries.

## Testing

- Keep tests with the behavior they verify.
- Prefer deterministic unit tests with substituted ports.
- Use the Compose integration harness for PostgreSQL behavior.
- Every bug fix requires a regression test when observable behavior can be reproduced.

## Delivery

- Use Conventional Commits without AI attribution.
- Keep each commit focused on a cohesive, independently verifiable work unit.
- Do not commit secrets, local environments, caches, or generated local tooling metadata.
