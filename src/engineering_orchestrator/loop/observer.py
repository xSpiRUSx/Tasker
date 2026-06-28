from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from engineering_orchestrator.executors.base import ExecutionResult
from engineering_orchestrator.services.git_service import GitService, GitStatusEntry
from engineering_orchestrator.services.validation_service import ValidationResult


class Observation(BaseModel):
    executor_result: ExecutionResult
    validation_result: ValidationResult
    git_status: str = ""
    status_entries: list[GitStatusEntry] = []
    changed_files: list[str] = []
    diff_stat: str = ""
    diff_patch: str = ""


class Observer:
    def __init__(self, git_service: GitService | None = None):
        self.git_service = git_service or GitService()

    def observe(
        self,
        worktree_path: str | Path | None,
        executor_result: ExecutionResult,
        validation_result: ValidationResult,
    ) -> Observation:
        if not worktree_path:
            return Observation(
                executor_result=executor_result,
                validation_result=validation_result,
                changed_files=executor_result.changed_files,
            )

        path = Path(worktree_path)
        status_entries = self.git_service.get_status_entries(path)
        changed_files = sorted({entry.path for entry in status_entries})
        return Observation(
            executor_result=executor_result,
            validation_result=validation_result,
            git_status=self.git_service.status(path),
            status_entries=status_entries,
            changed_files=changed_files,
            diff_stat=self.git_service.diff_stat(path),
            diff_patch=self.git_service.diff_patch(path),
        )
