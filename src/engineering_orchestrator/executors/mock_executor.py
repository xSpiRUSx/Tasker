from __future__ import annotations

from engineering_orchestrator.executors.base import ExecutionResult
from engineering_orchestrator.llm.prompt_bundle import PromptBundle
from engineering_orchestrator.llm.types import ModelDecision
from engineering_orchestrator.models import Task, TaskArtifact


class MockExecutor:
    def execute(
        self,
        task: Task,
        artifacts: list[TaskArtifact] | None = None,
        prompt_bundle: PromptBundle | None = None,
        model_decision: ModelDecision | None = None,
    ) -> ExecutionResult:
        artifact_count = len(artifacts or [])
        return ExecutionResult(
            status="success",
            changed_files=[],
            summary="Mock executor completed without modifying project files.",
            logs=f"Task {task.id} executed by mock executor with {artifact_count} input artifacts.",
        )
