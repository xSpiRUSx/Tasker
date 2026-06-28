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

    list_response = client.get("/tasks", params={"status": "awaiting_plan_approval"})
    assert list_response.status_code == 200
    assert [task["id"] for task in list_response.json()] == [payload["task_id"]]

    approvals_response = client.get(f"/tasks/{payload['task_id']}/approvals")
    assert approvals_response.status_code == 200
    assert approvals_response.json()[0]["gate"] == "plan"

    events_response = client.get(f"/tasks/{payload['task_id']}/events")
    assert events_response.status_code == 200
    assert [event["event_type"] for event in events_response.json()]

    context_response = client.get(f"/tasks/{payload['task_id']}/context")
    assert context_response.status_code == 200
    assert context_response.json()["task_id"] == payload["task_id"]

    approve_response = client.post(f"/tasks/{payload['task_id']}/approvals/plan", json={"decision": "approve"})
    assert approve_response.status_code == 200

    runs_response = client.get(f"/tasks/{payload['task_id']}/runs")
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert runs[0]["status"] == "passed"

    steps_response = client.get(f"/runs/{runs[0]['id']}/steps")
    assert steps_response.status_code == 200
    assert [step["step_type"] for step in steps_response.json()] == ["execute", "validate", "observe", "evaluate"]


def test_unified_ui_tasks_smoke(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))
    client.post("/tasks", json={"message": "Fix billing-api login bug"})

    response = client.get("/ui/tasks")

    assert response.status_code == 200
    assert "Tasker" in response.text
    assert "Fix billing-api login bug" in response.text
