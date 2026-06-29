from pathlib import Path
from dataclasses import replace
import shutil
import time

from fastapi.testclient import TestClient

from engineering_assistant.api import create_app
from engineering_orchestrator.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"succeeded", "failed", "cancelled"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Job did not finish: {job_id}")


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


def test_unified_route_prefers_specific_project_over_generic_dot_path(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))
    message = (
        "\u0420\u0435\u0430\u043b\u0438\u0437\u0443\u0439 \u0437\u0430\u0434\u0430\u0447\u0443 \u0432 "
        "\u043f\u0440\u043e\u0435\u043a\u0442\u0435 "
        "\u0441\u043d\u0435\u0436\u043d\u0430\u044f \u043a\u043e\u0440\u043e\u043b\u0435\u0432\u0430: "
        "\u0434\u043e\u0431\u0430\u0432\u044c "
        "\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443 "
        "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430."
    )

    response = client.post("/route", json={"message": message})

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "sq_erp_ext"
    assert payload["project_path"] == r"C:\Configuration\SQ_ERP\ERP_Ext"
    assert payload["recommended_tool_ids"] == ["1c-graph-metadata-mcp", "codex"]


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
    task_list = list_response.json()
    assert task_list["total"] == 1
    assert task_list["items"][0]["current_approval_gate"] == "plan"
    assert [task["id"] for task in task_list["items"]] == [payload["task_id"]]

    project_list_response = client.get("/tasks", params={"project_id": "solvix_zn", "q": payload["task_id"]})
    assert project_list_response.status_code == 200
    assert [task["id"] for task in project_list_response.json()["items"]] == [payload["task_id"]]

    approvals_response = client.get(f"/tasks/{payload['task_id']}/approvals")
    assert approvals_response.status_code == 200
    assert approvals_response.json()["items"][0]["gate"] == "plan"

    events_response = client.get(f"/tasks/{payload['task_id']}/events")
    assert events_response.status_code == 200
    assert [event["event_type"] for event in events_response.json()["items"]]

    artifacts_response = client.get(f"/tasks/{payload['task_id']}/artifacts")
    assert artifacts_response.status_code == 200
    artifact_id = next(artifact["id"] for artifact in artifacts_response.json() if artifact["kind"] == "task_index")
    artifact_response = client.get(f"/tasks/{payload['task_id']}/artifacts/by-id/{artifact_id}")
    assert artifact_response.status_code == 200
    assert artifact_response.json()["artifact"]["id"] == artifact_id
    assert payload["task_id"] in artifact_response.json()["content"]

    context_response = client.get(f"/tasks/{payload['task_id']}/context")
    assert context_response.status_code == 200
    assert context_response.json()["task_id"] == payload["task_id"]

    approve_response = client.post(f"/tasks/{payload['task_id']}/approvals/plan", json={"decision": "approve"})
    assert approve_response.status_code == 202
    approval_job = approve_response.json()
    assert approval_job["accepted"] is True
    assert approval_job["task_id"] == payload["task_id"]
    assert wait_for_job(client, approval_job["job_id"])["status"] == "succeeded"

    task_response = client.get(f"/tasks/{payload['task_id']}")
    assert task_response.status_code == 200
    assert task_response.json()["latest_job"]["status"] == "succeeded"

    runs_response = client.get(f"/tasks/{payload['task_id']}/runs")
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert runs[0]["status"] == "passed"

    steps_response = client.get(f"/runs/{runs[0]['id']}/steps")
    assert steps_response.status_code == 200
    assert [step["step_type"] for step in steps_response.json()] == ["execute", "validate", "observe", "evaluate"]


def test_unified_model_calls_endpoint_returns_token_usage(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = TestClient(app)
    response = client.post("/tasks", json={"message": "Fix billing-api login bug"})
    task_id = response.json()["task_id"]
    app.state.orchestrator.task_store.add_model_call(
        task_id,
        "run-1",
        "execute_code",
        "codex_cli",
        "gpt-5.5",
        provider="codex-estimated",
        prompt_chars=1200,
        prompt_tokens=300,
        completion_tokens=25,
        cached_prompt_tokens=100,
        reasoning_tokens=7,
        total_tokens=325,
        usage_source="test_usage",
        usage_is_estimated=False,
        status="success",
    )

    calls_response = client.get(f"/tasks/{task_id}/model-calls")

    assert calls_response.status_code == 200
    payload = calls_response.json()
    assert payload["items"][0]["model"] == "gpt-5.5"
    assert payload["items"][0]["prompt_tokens"] == 300
    assert payload["items"][0]["completion_tokens"] == 25
    assert payload["items"][0]["cached_prompt_tokens"] == 100
    assert payload["items"][0]["reasoning_tokens"] == 7
    assert payload["items"][0]["total_tokens"] == 325
    assert payload["items"][0]["usage_source"] == "test_usage"
    assert payload["items"][0]["usage_is_estimated"] is False


def test_unified_task_cancel_and_cors(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))
    response = client.post(
        "/tasks",
        json={
            "message": "Solvix_ZN: напиши простую обработку привет мир",
            "source": "test",
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    cancel_response = client.post(f"/tasks/{task_id}/cancel", json={"comment": "Cancelled by test"})
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    approvals_response = client.get(f"/tasks/{task_id}/approvals")
    assert approvals_response.status_code == 200
    assert approvals_response.json()["items"][0]["status"] == "cancelled"

    events_response = client.get(f"/tasks/{task_id}/events")
    assert events_response.status_code == 200
    assert "task_cancelled" in [event["event_type"] for event in events_response.json()["items"]]

    cors_response = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert cors_response.status_code == 200
    assert cors_response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_unified_router_config_can_be_edited(tmp_path):
    projects_path = tmp_path / "projects.yml"
    workflows_path = tmp_path / "workflows.yml"
    shutil.copy2(ROOT / "config" / "projects.yml", projects_path)
    shutil.copy2(ROOT / "config" / "workflows.yml", workflows_path)
    settings = replace(make_settings(tmp_path), projects_path=projects_path, workflows_path=workflows_path)
    client = TestClient(create_app(settings))

    response = client.get("/config/router")
    assert response.status_code == 200
    config = response.json()
    config["projects"].append(
        {
            "id": "ui_demo",
            "name": "UI Demo",
            "path": ".",
            "aliases": ["ui-demo"],
            "description": "Project added through the web config API.",
            "tools": ["codex"],
        }
    )
    config["workflows"].append(
        {
            "id": "ui_demo_question",
            "name": "UI demo question",
            "description": "Temporary workflow created by config endpoint test.",
            "project_ids": ["ui_demo"],
            "intents": ["question"],
            "task_kinds": ["question"],
            "complexity": ["trivial", "simple"],
            "required_tools": ["codex"],
            "approval_gates": [],
            "steps": ["Answer the question."],
        }
    )

    update_response = client.put("/config/router", json=config)

    assert update_response.status_code == 200
    updated = update_response.json()
    assert any(project["id"] == "ui_demo" for project in updated["projects"])
    assert any(workflow["id"] == "ui_demo_question" for workflow in updated["workflows"])

    route_response = client.post("/route", json={"message": "ui-demo: what is this project?"})
    assert route_response.status_code == 200
    assert route_response.json()["project_id"] == "ui_demo"


def test_unified_ui_tasks_smoke(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))
    client.post("/tasks", json={"message": "Fix billing-api login bug"})

    response = client.get("/ui/tasks")

    assert response.status_code == 200
    assert "Tasker" in response.text
    assert "Fix billing-api login bug" in response.text
