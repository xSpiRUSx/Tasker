from dataclasses import replace
from pathlib import Path
import subprocess

from engineering_orchestrator.api import Orchestrator
from engineering_orchestrator.models import ApprovalDecisionRequest, ContinueTaskRequest, CreateTaskRequest
from engineering_orchestrator.settings import Settings


def make_settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "orchestrator"
    return Settings(
        task_id_prefix="ENG",
        timezone="UTC",
        sqlite_path=tmp_path / "orchestrator.sqlite3",
        artifacts_root=tmp_path / "obsidian",
        task_folder_template="{task_id} - {project_id} {slug}",
        router_provider="mock",
        projects_path=root / "config" / "projects.yml",
        workflows_path=root / "config" / "workflows.yml",
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


def run_git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def test_full_mvp_lifecycle(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))

    response = orchestrator.create_task(
        CreateTaskRequest(message="Fix billing-api login bug", source="test", user_id="alexey")
    )

    assert response.status == "awaiting_plan_approval"
    assert response.current_approval_gate == "plan"
    assert response.project_id == "billing-api"
    assert "billing-api" in response.artifacts_dir

    task = orchestrator.decide_approval(response.task_id, "plan", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "awaiting_diff_approval"
    assert orchestrator.task_store.get_pending_approval(task.id, "diff") is not None
    assert orchestrator.task_store.get_artifact(task.id, "run_report") is not None
    assert orchestrator.task_store.get_artifact(task.id, "run_report_json") is not None
    assert orchestrator.task_store.get_artifact(task.id, "evaluation_report") is not None
    runs = orchestrator.list_runs(task.id)
    assert len(runs) == 1
    assert runs[0].status == "passed"
    assert [step.step_type for step in orchestrator.list_steps(runs[0].id)] == ["execute", "validate", "observe", "evaluate"]

    task = orchestrator.decide_approval(response.task_id, "diff", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "awaiting_commit_approval"
    assert orchestrator.task_store.get_pending_approval(task.id, "commit") is not None

    closed = orchestrator.decide_approval(response.task_id, "commit", ApprovalDecisionRequest(decision="approve"))

    assert closed.status == "closed"
    assert orchestrator.task_store.get_artifact(closed.id, "final_report") is not None


def test_plan_approval_can_be_disabled(tmp_path):
    settings = replace(make_settings(tmp_path), require_plan_approval=False)
    orchestrator = Orchestrator(settings)

    response = orchestrator.create_task(
        CreateTaskRequest(message="Fix billing-api login bug", source="test", user_id="alexey")
    )

    assert response.status == "awaiting_diff_approval"
    assert response.current_approval_gate == "diff"
    assert orchestrator.task_store.get_artifact(response.task_id, "todo", version=1) is not None
    assert orchestrator.task_store.get_pending_approval(response.task_id, "plan") is None
    assert orchestrator.task_store.get_pending_approval(response.task_id, "diff") is not None
    events = [event.event_type for event in orchestrator.task_store.list_events(response.task_id)]
    assert "plan_approval_skipped" in events


def test_diff_approval_can_be_disabled(tmp_path):
    settings = replace(make_settings(tmp_path), require_diff_approval=False)
    orchestrator = Orchestrator(settings)
    response = orchestrator.create_task(CreateTaskRequest(message="Fix billing-api login bug"))

    task = orchestrator.decide_approval(response.task_id, "plan", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "awaiting_commit_approval"
    assert orchestrator.task_store.get_pending_approval(task.id, "diff") is None
    assert orchestrator.task_store.get_pending_approval(task.id, "commit") is not None
    assert orchestrator.task_store.get_artifact(task.id, "diff_summary") is not None
    events = [event.event_type for event in orchestrator.task_store.list_events(task.id)]
    assert "diff_approval_skipped" in events


def test_config_change_requires_config_gate_after_plan(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))

    response = orchestrator.create_task(
        CreateTaskRequest(message="Login fails in billing-api after config update", source="test", user_id="alexey")
    )

    task = orchestrator.decide_approval(response.task_id, "plan", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "awaiting_config_approval"
    assert orchestrator.task_store.get_pending_approval(task.id, "config_change") is not None
    assert orchestrator.task_store.get_artifact(task.id, "execution_log") is None

    task = orchestrator.decide_approval(task.id, "config_change", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "awaiting_diff_approval"
    assert orchestrator.task_store.get_pending_approval(task.id, "diff") is not None

    task = orchestrator.decide_approval(task.id, "diff", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "awaiting_commit_approval"
    assert orchestrator.task_store.get_pending_approval(task.id, "commit") is not None


def test_reject_plan(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    response = orchestrator.create_task(CreateTaskRequest(message="Fix generic login bug"))

    task = orchestrator.decide_approval(response.task_id, "plan", ApprovalDecisionRequest(decision="reject", comment="Need more detail"))

    assert task.status == "plan_rejected"


def test_reject_plan_and_message_creates_v2_plan(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    response = orchestrator.create_task(CreateTaskRequest(message="Fix generic login bug"))

    orchestrator.decide_approval(
        response.task_id,
        "plan",
        ApprovalDecisionRequest(decision="reject", comment="Need more detail"),
    )
    task = orchestrator.continue_task(response.task_id, ContinueTaskRequest(message="Limit the change to auth.py"))

    assert task.status == "awaiting_plan_approval"
    assert orchestrator.task_store.get_artifact(task.id, "todo", version=2) is not None
    approval = orchestrator.task_store.get_pending_approval(task.id, "plan")
    assert approval is not None
    assert approval.requested_payload["plan_version"] == 2


def test_validation_failure_stops_before_diff_approval(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    orchestrator.projects.projects[0]["test_commands"] = ["python -c \"import sys; print('failed validation'); sys.exit(5)\""]
    response = orchestrator.create_task(CreateTaskRequest(message="Fix billing-api login bug"))

    task = orchestrator.task_store.get_task(response.task_id)
    task.worktree_path = str(tmp_path)
    orchestrator.task_store.update_task(task)

    task = orchestrator.decide_approval(response.task_id, "plan", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "validation_failed"
    assert orchestrator.task_store.get_pending_approval(task.id, "diff") is None
    validation = orchestrator.task_store.get_artifact(task.id, "validation_report")
    assert validation is not None
    assert "failed validation" in orchestrator.artifact_store.read_text(validation)
    assert orchestrator.task_store.get_artifact(task.id, "validation_command_output", version=1) is not None


def test_question_only_closes_without_approval(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))

    response = orchestrator.create_task(CreateTaskRequest(message="How does billing-api login work?"))

    assert response.status == "closed"
    assert response.current_approval_gate is None
    assert response.workflow_id == "question_only"
    assert orchestrator.task_store.list_approvals(response.task_id) == []
    assert orchestrator.task_store.get_artifact(response.task_id, "answer") is not None
    assert orchestrator.task_store.get_artifact(response.task_id, "todo") is None


def test_working_memory_is_written_and_rebuildable(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))

    response = orchestrator.create_task(CreateTaskRequest(message="Fix billing-api login bug"))

    assert orchestrator.task_store.get_artifact(response.task_id, "working_memory") is not None
    assert orchestrator.task_store.get_artifact(response.task_id, "working_memory_json") is not None
    memory = orchestrator.get_context(response.task_id)
    assert memory.task_id == response.task_id
    assert memory.route_decision["project_id"] == "billing-api"
    assert memory.project_profile["id"] == "billing-api"
    assert memory.workflow_policy["id"] == "simple_dev_no_config"
    rebuilt = orchestrator.rebuild_context(response.task_id)
    assert rebuilt.task_id == response.task_id


def test_list_tasks_can_filter_by_status(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    first = orchestrator.create_task(CreateTaskRequest(message="Fix generic login bug"))
    second = orchestrator.create_task(CreateTaskRequest(message="How does billing-api login work?"))

    all_tasks = orchestrator.list_tasks()
    awaiting_plan = orchestrator.list_tasks("awaiting_plan_approval")
    closed = orchestrator.list_tasks("closed")

    assert {task.id for task in all_tasks} == {first.task_id, second.task_id}
    assert [task.id for task in awaiting_plan] == [first.task_id]
    assert [task.id for task in closed] == [second.task_id]
    assert [task.id for task in orchestrator.list_tasks(project_id="billing-api")] == [second.task_id, first.task_id]


def test_commit_requires_fresh_diff_approval(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tasker@example.local")
    run_git(repo, "config", "user.name", "Tasker Tests")
    (repo / "tracked.txt").write_text("before\n", encoding="utf-8", newline="\n")
    run_git(repo, "add", "tracked.txt")
    run_git(repo, "commit", "-m", "initial")

    orchestrator = Orchestrator(make_settings(tmp_path))
    orchestrator.projects.projects[0]["test_commands"] = []
    response = orchestrator.create_task(CreateTaskRequest(message="Fix billing-api login bug"))
    task = orchestrator.task_store.get_task(response.task_id)
    task.worktree_path = str(repo)
    orchestrator.task_store.update_task(task)

    task = orchestrator.decide_approval(response.task_id, "plan", ApprovalDecisionRequest(decision="approve"))
    assert task.status == "awaiting_diff_approval"
    task = orchestrator.decide_approval(response.task_id, "diff", ApprovalDecisionRequest(decision="approve"))
    assert task.status == "awaiting_commit_approval"

    (repo / "tracked.txt").write_text("after approval\n", encoding="utf-8", newline="\n")
    task = orchestrator.decide_approval(response.task_id, "commit", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "changes_requested"
    assert "changed files differ" in orchestrator.artifact_store.read_text(
        orchestrator.task_store.get_artifact(task.id, "commit_result")
    )
