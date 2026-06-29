from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from engineering_orchestrator.executors.base import ExecutionResult
from engineering_orchestrator.llm.prompt_bundle import PromptBundle
from engineering_orchestrator.llm.types import ModelDecision
from engineering_orchestrator.models import Task, TaskArtifact


class CodexExecutor:
    def __init__(
        self,
        artifacts_root: str | Path,
        codex_bin: str = "codex",
        timeout_seconds: int = 1800,
    ):
        self.artifacts_root = Path(artifacts_root)
        self.codex_bin = codex_bin
        self.timeout_seconds = timeout_seconds

    def execute(
        self,
        task: Task,
        artifacts: list[TaskArtifact] | None = None,
        prompt_bundle: PromptBundle | None = None,
        model_decision: ModelDecision | None = None,
    ) -> ExecutionResult:
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
        if model_decision and model_decision.model not in {"", "none", "mock"}:
            command.extend(["--model", model_decision.model])

        if prompt_bundle is None:
            return ExecutionResult(
                status="failed",
                changed_files=[],
                summary="CodexExecutor requires a PromptBundle built by PromptBudgeter.",
            )
        prompt = prompt_bundle.prompt
        try:
            completed = subprocess.run(
                self._windows_command(command),
                cwd=worktree_path,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(
                status="failed",
                changed_files=[],
                summary=f"Codex CLI timed out after {self.timeout_seconds} seconds.",
                logs=self._timeout_logs(exc),
                command=command,
                prompt=prompt,
                stdout=self._decode_timeout_output(exc.stdout),
                stderr=self._decode_timeout_output(exc.stderr),
                timed_out=True,
            )

        logs = self._logs(completed)
        if completed.returncode != 0:
            return ExecutionResult(
                status="failed",
                changed_files=[],
                summary=f"Codex CLI failed with exit code {completed.returncode}.",
                logs=logs,
                command=command,
                prompt=prompt,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )

        return ExecutionResult(
            status="success",
            changed_files=[],
            summary="Codex CLI execution completed. Inspect the generated diff before approving.",
            logs=logs,
            command=command,
            prompt=prompt,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

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

    def _timeout_logs(self, exc: subprocess.TimeoutExpired) -> str:
        chunks = []
        stdout = self._decode_timeout_output(exc.stdout).strip()
        stderr = self._decode_timeout_output(exc.stderr).strip()
        if stdout:
            chunks.append("STDOUT\n" + stdout)
        if stderr:
            chunks.append("STDERR\n" + stderr)
        chunks.append(f"Process timed out after {self.timeout_seconds} seconds.")
        return "\n\n".join(chunks)

    def _decode_timeout_output(self, value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value
