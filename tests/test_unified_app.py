from pathlib import Path

from fastapi.testclient import TestClient

from engineering_assistant.api import create_app
from engineering_orchestrator.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        task_id_prefix="ENG",
        timezone="UTC",
        sqlite_path=tmp_path / "orchestrator.sqlite3",
        artifacts_root=tmp_path / "obsidian",
        task_folder_template="{task_id} - {project_id} {slug}",
        router_provider="mock",
        projects_path=ROOT / "config" / "projects.yml",
        workflows_path=ROOT / "config" / "workflows.yml",
        planner_provider="mock",
        planner_model=None,
        planner_timeout_seconds=900,
        default_executor="mock",
        codex_bin="codex",
        codex_model=None,
        codex_timeout_seconds=1800,
        worktrees_root=tmp_path / "worktrees",
        branch_template="ai/{task_id}-{slug}",
        run_tests_after_execution=True,
        require_plan_approval=True,
        require_diff_approval=True,
        require_commit_approval=True,
    )


def test_unified_route_endpoint_uses_internal_router(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))

    response = client.post("/route", json={"message": "Solvix_ZN: напиши простую обработку привет мир"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "solvix_zn"
    assert payload["workflow_id"] == "simple_external_development"
    assert payload["approval_gates"] == ["plan", "diff", "commit"]


def test_unified_tasks_endpoint_uses_router_decision(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))

    response = client.post(
        "/tasks",
        json={
            "message": "Solvix_ZN: напиши простую обработку привет мир",
            "source": "test",
            "user_id": "alexey",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "awaiting_plan_approval"
    assert payload["project_id"] == "solvix_zn"
    assert payload["workflow_id"] == "simple_external_development"

    task_response = client.get(f"/tasks/{payload['task_id']}")
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["route_decision"]["recommended_tool_ids"] == ["codex"]
