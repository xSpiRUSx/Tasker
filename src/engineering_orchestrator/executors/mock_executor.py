from __future__ import annotations

from engineering_orchestrator.executors.base import ExecutionResult
from engineering_orchestrator.models import Task, TaskArtifact


class MockExecutor:
    def execute(self, task: Task, artifacts: list[TaskArtifact]) -> ExecutionResult:
        return ExecutionResult(
            status="success",
            changed_files=[],
            summary="Mock executor completed without modifying project files.",
            logs=f"Task {task.id} executed by mock executor with {len(artifacts)} input artifacts.",
        )
