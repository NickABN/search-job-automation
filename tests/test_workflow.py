import re
from pathlib import Path

WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "scheduled-job-pipeline.yml"
)


def _top_level_keys(workflow: str) -> set[str]:
    return {
        line.split(":", maxsplit=1)[0]
        for line in workflow.splitlines()
        if line and not line.startswith(" ") and ":" in line
    }


def _step_positions(workflow: str) -> list[int]:
    names = [
        "Install application",
        "Resolve digest slot",
        "Wait for Neon PostgreSQL readiness",
        "Apply database migrations",
        "Ingest Bitso Greenhouse jobs",
        "Rank top jobs",
        "Send resolved digest",
    ]
    return [workflow.index(f"- name: {name}") for name in names]


def test_production_workflow_has_only_trusted_triggers_and_exact_mapping() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert _top_level_keys(workflow) == {
        "name",
        "on",
        "permissions",
        "concurrency",
        "jobs",
    }
    assert "  schedule:" in workflow
    assert '    - cron: "0 15 * * *"' in workflow
    assert '    - cron: "0 0 * * *"' in workflow
    assert "  workflow_dispatch:" in workflow
    assert "type: choice" in workflow
    assert "          - morning" in workflow
    assert "          - evening" in workflow
    assert '"0 15 * * *") slot=morning' in workflow
    assert '"0 0 * * *") slot=evening' in workflow
    assert '*) echo "Unsupported schedule event" >&2; exit 1 ;;' in workflow
    assert all(
        trigger not in workflow
        for trigger in ("pull_request", "pull_request_target", "push:", "workflow_call")
    )


def test_production_workflow_has_minimal_permissions_and_safe_concurrency() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read\n\nconcurrency:" in workflow
    assert "  group: scheduled-job-pipeline" in workflow
    assert "  cancel-in-progress: false" in workflow
    assert "    timeout-minutes: 15" in workflow
    assert '          python-version: "3.12"' in workflow
    assert "          cache-dependency-path: pyproject.toml" in workflow


def test_production_workflow_projects_secrets_only_to_job_environment() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    secret_lines = [line for line in workflow.splitlines() if "secrets." in line]

    assert [line.strip() for line in secret_lines] == [
        "DATABASE_URL: ${{ secrets.DATABASE_URL }}",
        "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}",
        "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}",
    ]
    assert all(line.startswith("      ") for line in secret_lines)
    assert all(
        "secrets." not in line
        for line in workflow.splitlines()
        if line.strip().startswith("run:")
    )


def test_production_workflow_orders_pipeline_steps_and_pins_actions() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert _step_positions(workflow) == sorted(_step_positions(workflow))
    assert re.findall(
        r"uses: actions/[^@]+@([0-9a-f]{40})$", workflow, re.MULTILINE
    ) == [
        "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "5fda3b95a4ea91299a34e894583c3862153e4b97",
    ]
    assert "--board-token bitso --company Bitso" in workflow
    assert "rank-jobs --limit 20" in workflow
    assert 'send-job-digest --slot "$DIGEST_SLOT"' in workflow
