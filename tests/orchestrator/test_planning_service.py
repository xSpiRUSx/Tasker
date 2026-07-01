import json
import subprocess

from engineering_orchestrator.models import Task
from engineering_orchestrator.services.planning_service import CodexPlanWriter
from engineering_orchestrator.services.task_store import utc_now
from task_router.models import RouteDecision


def test_codex_plan_writer_passes_selected_model(monkeypatch, tmp_path):
    captured: dict[str, list[str]] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        payload = {
            "spec_markdown": "",
            "todo_markdown": "# Todo\n",
            "test_plan_markdown": "# Test plan\n",
            "approval_markdown": "# Approval\n",
            "planning_notes": "planned",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    now = utc_now()
    task = Task(
        id="ENG-TEST",
        status="planning",
        user_message="Plan it",
        project_id="demo",
        project_name="Demo",
        project_path=str(tmp_path),
        workflow_id="simple",
        workflow_name="Simple",
        risk_level="low",
        created_at=now,
        updated_at=now,
    )
    route = RouteDecision(
        input_text="Plan it",
        normalized_task="Plan it",
        project_id="demo",
        project_name="Demo",
        project_path=str(tmp_path),
        project_confidence=1.0,
        complexity="simple",
        complexity_score=2,
        intent="code_change",
        task_kind="feature",
        risk_level="low",
        risk_flags=[],
        workflow_id="simple",
        workflow_name="Simple",
        workflow_confidence=1.0,
        requires_spec=False,
        requires_tests=True,
        requires_review=True,
        requires_config_approval=False,
        requires_deploy_prep=False,
        approval_gates=["plan"],
        recommended_tool_ids=["codex"],
        confidence=1.0,
        rationale="test",
        missing_info=[],
        assumptions=[],
        next_steps=[],
        warnings=[],
    )

    CodexPlanWriter(codex_bin="codex").write_plan(task, route, "context", model="gpt-5.5")

    command_text = " ".join(captured["command"])
    assert "--model gpt-5.5" in command_text
