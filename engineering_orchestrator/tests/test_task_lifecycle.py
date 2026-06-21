from pathlib import Path

from engineering_orchestrator.api import Orchestrator
from engineering_orchestrator.models import ApprovalDecisionRequest, CreateTaskRequest
from engineering_orchestrator.settings import Settings


def make_settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parent.parent
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

    task = orchestrator.decide_approval(response.task_id, "diff", ApprovalDecisionRequest(decision="approve"))

    assert task.status == "awaiting_commit_approval"
    assert orchestrator.task_store.get_pending_approval(task.id, "commit") is not None

    closed = orchestrator.decide_approval(response.task_id, "commit", ApprovalDecisionRequest(decision="approve"))

    assert closed.status == "closed"
    assert orchestrator.task_store.get_artifact(closed.id, "final_report") is not None


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
