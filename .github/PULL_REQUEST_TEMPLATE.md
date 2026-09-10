## Linked issue (required)

Use one closing reference to an approved issue, for example:

`Closes #123`

## PR type (check exactly one)

- [ ] `type:bug` — bug fix
- [ ] `type:feature` — new feature
- [ ] `type:docs` — documentation only
- [ ] `type:refactor` — code refactoring
- [ ] `type:chore` — maintenance or tooling
- [ ] `type:breaking-change` — breaking change

The PR must have exactly one `type:*` label matching the selected type.

## Summary

-

## Changes

| File or area | Change |
| --- | --- |
|  |  |

## Test plan

- [ ] Unit or integration tests added or updated where behavior changed
- [ ] Relevant Python tests pass (for example, `pytest`)
- [ ] Ruff and strict mypy checks pass, when applicable
- [ ] FastAPI endpoints were verified with appropriate request/response tests, when applicable
- [ ] PostgreSQL behavior was verified with the Compose integration harness, when applicable
- [ ] Migration upgrade and downgrade were verified, when applicable
- [ ] Manual verification completed, when applicable

## Chained PR context

If this is part of a sequence, link the previous and next PRs and state which review boundary this PR covers.

## Contributor checklist

- [ ] Linked an approved issue with `Closes #N`, `Fixes #N`, or `Resolves #N`
- [ ] Added exactly one matching `type:*` label
- [ ] Used a Conventional Commit message
- [ ] Did not add a `Co-Authored-By` trailer or AI attribution
- [ ] Kept secrets and sensitive payloads out of code, logs, and test fixtures
- [ ] Updated documentation when behavior or public usage changed
