from __future__ import annotations

from datetime import datetime, timezone

from engineering_orchestrator.executors.codex_executor import CodexExecutor
from engineering_orchestrator.llm.prompt_budgeter import MAX_PROMPT_ARTIFACT_CHARS, PromptBudgeter
from engineering_orchestrator.models import Task, TaskArtifact


def make_task() -> Task:
    return Task(
        id="ENG-TEST-00001",
        status="executing",
        user_message="Fix the task",
        project_id="billing-api",
        project_name="Billing API",
        workflow_id="simple_dev",
        workflow_name="Simple dev",
        risk_level="medium",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        worktree_path="C:/repo",
    )


def make_artifact(kind: str, relative_path: str, version: int | None = None) -> TaskArtifact:
    return TaskArtifact(
        id=f"artifact-{kind}-{version or 'latest'}",
        task_id="ENG-TEST-00001",
        kind=kind,  # type: ignore[arg-type]
        version=version,
        title=f"{kind} {version or ''}".strip(),
        relative_path=relative_path,
        content_hash="hash",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_budgeter(tmp_path) -> PromptBudgeter:
    config = tmp_path / "token_budgets.yml"
    config.write_text(
        """
global:
  max_prompt_chars: 300000
  max_single_artifact_chars: 40000
forbidden_prompt_artifacts:
  - events.md
  - 07-executor-prompt.md
  - 07-executor-stdout.md
  - 07-executor-stderr.md
  - 07-run.json
  - traces/*.jsonl
  - runtime/*
""",
        encoding="utf-8",
    )
    return PromptBudgeter(config)


def test_codex_prompt_uses_latest_planning_artifacts_and_skips_runtime_logs(tmp_path):
    (tmp_path / "task").mkdir()
    (tmp_path / "task" / "03-spec.v1.md").write_text("old spec", encoding="utf-8")
    (tmp_path / "task" / "03-spec.v2.md").write_text("new spec", encoding="utf-8")
    (tmp_path / "task" / "04-todo.v2.md").write_text("todo", encoding="utf-8")
    (tmp_path / "task" / "07-executor-stderr.md").write_text("runtime stderr " * 1000, encoding="utf-8")
    (tmp_path / "task" / "10-diff.patch").write_text("diff patch " * 1000, encoding="utf-8")

    bundle = make_budgeter(tmp_path).build_bundle(
        make_task(),
        "execute_code",
        [
            make_artifact("spec", "task/03-spec.v1.md", version=1),
            make_artifact("spec", "task/03-spec.v2.md", version=2),
            make_artifact("todo", "task/04-todo.v2.md", version=2),
            make_artifact("executor_stderr", "task/07-executor-stderr.md"),
            make_artifact("diff_patch", "task/10-diff.patch"),
        ],
        tmp_path,
    )
    prompt = bundle.prompt

    assert "new spec" in prompt
    assert "old spec" not in prompt
    assert "todo" in prompt
    assert "runtime stderr" not in prompt
    assert "diff patch" not in prompt


def test_codex_prompt_truncates_large_allowed_artifacts(tmp_path):
    (tmp_path / "task").mkdir()
    large_content = "x" * (MAX_PROMPT_ARTIFACT_CHARS + 10)
    (tmp_path / "task" / "03-spec.v1.md").write_text(large_content, encoding="utf-8")

    prompt = make_budgeter(tmp_path).build_bundle(
        make_task(),
        "execute_code",
        [make_artifact("spec", "task/03-spec.v1.md", version=1)],
        tmp_path,
    ).prompt

    assert "[Artifact truncated before sending to runtime." in prompt
    assert len(prompt) < len(large_content) + 2000


def test_codex_correction_prompt_uses_compact_correction_artifacts(tmp_path):
    (tmp_path / "task").mkdir()
    (tmp_path / "task" / "12-correction-001.md").write_text("remove helper procedures", encoding="utf-8")
    (tmp_path / "task" / "12-correction-001-context.md").write_text("allowed files: auth.py", encoding="utf-8")
    (tmp_path / "task" / "07-executor-stdout.md").write_text("old stdout " * 1000, encoding="utf-8")

    bundle = make_budgeter(tmp_path).build_bundle(
        make_task(),
        "execute_micro_correction",
        [
            make_artifact("correction_request", "task/12-correction-001.md", version=1),
            make_artifact("correction_context", "task/12-correction-001-context.md", version=1),
            make_artifact("executor_stdout", "task/07-executor-stdout.md"),
        ],
        tmp_path,
    )
    prompt = bundle.prompt

    assert "You are applying a user-requested correction" in prompt
    assert "remove helper procedures" in prompt
    assert "allowed files: auth.py" in prompt
    assert "old stdout" not in prompt
    assert "Implement the approved plan" not in prompt


def test_codex_executor_requires_prompt_bundle(tmp_path):
    task = make_task()
    task.worktree_path = str(tmp_path)
    executor = CodexExecutor(tmp_path)

    result = executor.execute(task, artifacts=[])

    assert result.status == "failed"
    assert "PromptBundle" in result.summary
