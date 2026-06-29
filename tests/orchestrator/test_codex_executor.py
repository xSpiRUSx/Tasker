from __future__ import annotations

from datetime import datetime, timezone

from engineering_orchestrator.executors.codex_executor import CodexExecutor, MAX_PROMPT_ARTIFACT_CHARS
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


def test_codex_prompt_uses_latest_planning_artifacts_and_skips_runtime_logs(tmp_path):
    (tmp_path / "task").mkdir()
    (tmp_path / "task" / "03-spec.v1.md").write_text("old spec", encoding="utf-8")
    (tmp_path / "task" / "03-spec.v2.md").write_text("new spec", encoding="utf-8")
    (tmp_path / "task" / "04-todo.v2.md").write_text("todo", encoding="utf-8")
    (tmp_path / "task" / "07-executor-stderr.md").write_text("runtime stderr " * 1000, encoding="utf-8")
    (tmp_path / "task" / "10-diff.patch").write_text("diff patch " * 1000, encoding="utf-8")

    executor = CodexExecutor(tmp_path)
    prompt = executor._build_prompt(
        make_task(),
        [
            make_artifact("spec", "task/03-spec.v1.md", version=1),
            make_artifact("spec", "task/03-spec.v2.md", version=2),
            make_artifact("todo", "task/04-todo.v2.md", version=2),
            make_artifact("executor_stderr", "task/07-executor-stderr.md"),
            make_artifact("diff_patch", "task/10-diff.patch"),
        ],
    )

    assert "new spec" in prompt
    assert "old spec" not in prompt
    assert "todo" in prompt
    assert "runtime stderr" not in prompt
    assert "diff patch" not in prompt


def test_codex_prompt_truncates_large_allowed_artifacts(tmp_path):
    (tmp_path / "task").mkdir()
    large_content = "x" * (MAX_PROMPT_ARTIFACT_CHARS + 10)
    (tmp_path / "task" / "03-spec.v1.md").write_text(large_content, encoding="utf-8")

    executor = CodexExecutor(tmp_path)
    prompt = executor._build_prompt(make_task(), [make_artifact("spec", "task/03-spec.v1.md", version=1)])

    assert "[Artifact truncated before sending to Codex executor." in prompt
    assert len(prompt) < len(large_content) + 2000
