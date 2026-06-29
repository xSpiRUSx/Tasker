from pathlib import Path
import threading
import time

from engineering_orchestrator.api import Orchestrator
from engineering_orchestrator.llm import ModelSelectionRequest
from engineering_orchestrator.llm.prompt_budgeter import PromptBudgetError
from engineering_orchestrator.models import CreateTaskRequest, TaskArtifact
from engineering_orchestrator.services.job_runner import JobRunner
from engineering_orchestrator.services.task_store import TaskStore, utc_now
from tests.orchestrator.test_task_lifecycle import make_settings


def test_model_policy_routes_core_operations(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))

    route = orchestrator.model_selector.select(ModelSelectionRequest(operation="route_task"))
    simple = orchestrator.model_selector.select(
        ModelSelectionRequest(operation="create_simple_plan", workflow_id="simple_dev_no_config", project_id="billing-api")
    )
    high_1c = orchestrator.model_selector.select(
        ModelSelectionRequest(
            operation="create_1c_business_spec",
            workflow_id="1c_business_logic_change",
            project_id="sq_erp_ext",
            risk_level="high",
        )
    )
    micro = orchestrator.model_selector.select(
        ModelSelectionRequest(
            operation="execute_micro_correction",
            workflow_id="simple_dev_no_config",
            project_id="billing-api",
            correction_mode="micro_correction",
            requires_code_execution=True,
        )
    )

    assert route.target_id == "deterministic"
    assert simple.target_id == "gpt55_medium"
    assert high_1c.target_id == "gpt55_high"
    assert micro.target_id == "codex_spark"


def test_route_strategy_resolves_to_first_target_without_mock_fallback(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))

    decision = orchestrator.model_selector.select(
        ModelSelectionRequest(operation="review_diff", workflow_id="simple_dev_no_config", project_id="billing-api")
    )

    assert decision.target_id == "deterministic"
    assert "strategy `deterministic_then_gpt55_medium`" in decision.reason


def test_unknown_model_route_fails_loudly(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    orchestrator.projects.projects[0]["model_overrides"] = {"planning": "missing_strategy"}

    try:
        orchestrator.model_selector.select(
            ModelSelectionRequest(operation="create_simple_plan", workflow_id="simple_dev_no_config", project_id="billing-api")
        )
    except KeyError as exc:
        assert "missing_strategy" in str(exc)
    else:
        raise AssertionError("Unknown target/strategy did not fail")


def test_project_model_override_wins_over_workflow_default(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    orchestrator.projects.projects[0]["model_overrides"] = {"planning": "gpt55_high"}

    decision = orchestrator.model_selector.select(
        ModelSelectionRequest(operation="create_simple_plan", workflow_id="simple_dev_no_config", project_id="billing-api")
    )

    assert decision.target_id == "gpt55_high"
    assert "project override" in decision.reason


def test_prompt_budget_excludes_runtime_artifacts_and_fails_before_llm(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    task = orchestrator.task_store.create_task("Prompt budget test", prefix="ENG")
    task.artifacts_dir = orchestrator.artifact_store.create_task_folder(task, task.user_message)
    orchestrator.task_store.update_task(task)
    folder = Path(task.artifacts_dir)
    root = orchestrator.artifact_store.root_path
    (root / folder / "02-context.md").write_text("small context", encoding="utf-8")
    (root / folder / "07-executor-stdout.md").write_text("old stdout " * 1000, encoding="utf-8")
    now = utc_now()
    artifacts = [
        TaskArtifact(
            id="artifact-context",
            task_id=task.id,
            kind="context_summary",
            title="Context",
            relative_path=(folder / "02-context.md").as_posix(),
            content_hash="context",
            created_at=now,
            updated_at=now,
        ),
        TaskArtifact(
            id="artifact-stdout",
            task_id=task.id,
            kind="executor_stdout",
            title="Old stdout",
            relative_path=(folder / "07-executor-stdout.md").as_posix(),
            content_hash="stdout",
            created_at=now,
            updated_at=now,
        ),
    ]

    manifest = orchestrator.prompt_budgeter.build_manifest("execute_code", artifacts, root, base_prompt_chars=400000)

    assert [item.kind for item in manifest.excluded_artifacts] == ["executor_stdout"]
    assert manifest.status == "prompt_too_large"
    try:
        orchestrator.prompt_budgeter.ensure_within_budget(manifest)
    except PromptBudgetError:
        pass
    else:
        raise AssertionError("PromptBudgetError was not raised")


def test_job_runner_records_result_and_cancellation(tmp_path):
    store = TaskStore(tmp_path / "jobs.sqlite3")
    task = store.create_task("Job test", prefix="ENG")
    runner = JobRunner(store)

    done = runner.enqueue(task.id, "instant", lambda: {"ok": True}, input={"x": 1})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = store.get_job(done.id)
        if job.status == "succeeded":
            break
        time.sleep(0.01)
    assert store.get_job(done.id).result == {"ok": True}

    blocker = threading.Event()
    queued = runner.enqueue(task.id, "queued", lambda: blocker.wait(0.2), input={})
    cancelled = runner.cancel(queued.id)
    assert cancelled.status in {"cancelled", "running"}
    blocker.set()
