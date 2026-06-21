from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from engineering_orchestrator.executors.base import ExecutionResult
from engineering_orchestrator.models import Task, TaskArtifact


class CodexExecutor:
    def __init__(
        self,
        artifacts_root: str | Path,
        codex_bin: str = "codex",
        model: str | None = None,
        timeout_seconds: int = 1800,
    ):
        self.artifacts_root = Path(artifacts_root)
        self.codex_bin = codex_bin
        self.model = model
        self.timeout_seconds = timeout_seconds

    def execute(self, task: Task, artifacts: list[TaskArtifact]) -> ExecutionResult:
        if not task.worktree_path:
            return ExecutionResult(
                status="failed",
                changed_files=[],
                summary="CodexExecutor requires task.worktree_path, but it was not set.",
            )

        worktree_path = Path(task.worktree_path)
        if not worktree_path.exists():
            return ExecutionResult(
                status="failed",
                changed_files=[],
                summary=f"Codex worktree does not exist: {worktree_path}",
            )

        command = [self._resolve_codex_bin(), "exec", "-", "--skip-git-repo-check"]
        if self.model:
            command.extend(["--model", self.model])

        completed = subprocess.run(
            self._windows_command(command),
            cwd=worktree_path,
            input=self._build_prompt(task, artifacts),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )

        logs = self._logs(completed)
        if completed.returncode != 0:
            return ExecutionResult(
                status="failed",
                changed_files=[],
                summary=f"Codex CLI failed with exit code {completed.returncode}.",
                logs=logs,
            )

        return ExecutionResult(
            status="success",
            changed_files=[],
            summary="Codex CLI execution completed. Inspect the generated diff before approving.",
            logs=logs,
        )

    def _build_prompt(self, task: Task, artifacts: list[TaskArtifact]) -> str:
        artifact_sections = []
        for artifact in artifacts:
            if artifact.kind in {"task_index", "events"}:
                continue
            path = self.artifacts_root / artifact.relative_path
            if not path.exists():
                continue
            artifact_sections.append(
                f"## Artifact: {artifact.title} ({artifact.kind})\n\n"
                f"Path: {path}\n\n"
                f"```markdown\n{path.read_text(encoding='utf-8')}\n```"
            )

        return f"""
You are Codex running inside an approved task worktree.

Task ID: {task.id}
Project: {task.project_id} / {task.project_name}
Workflow: {task.workflow_id} / {task.workflow_name}
Risk: {task.risk_level}

Original user request:
{task.user_message}

Instructions:
- Work only inside the current working directory.
- Implement the approved plan using the artifacts below.
- Do not commit changes.
- Do not change secrets.
- Do not deploy.
- Prefer small, focused changes.
- Run relevant local checks when they are obvious and safe.
- If the task cannot be completed, leave clear notes in your final output.

Artifacts:

{chr(10).join(artifact_sections) if artifact_sections else "No readable artifacts were provided."}
""".strip()

    def _resolve_codex_bin(self) -> str:
        return shutil.which(self.codex_bin) or self.codex_bin

    def _windows_command(self, command: list[str]) -> list[str]:
        if os.name != "nt":
            return command
        suffix = Path(command[0]).suffix.lower()
        if suffix in {".cmd", ".bat"}:
            return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(command)]
        return command

    def _logs(self, completed: subprocess.CompletedProcess[str]) -> str:
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        chunks = []
        if stdout:
            chunks.append("STDOUT\n" + stdout)
        if stderr:
            chunks.append("STDERR\n" + stderr)
        return "\n\n".join(chunks)
