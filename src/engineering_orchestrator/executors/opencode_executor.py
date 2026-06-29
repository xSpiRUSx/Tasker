from __future__ import annotations

from engineering_orchestrator.executors.base import ExecutionResult
from engineering_orchestrator.llm.prompt_bundle import PromptBundle
from engineering_orchestrator.llm.types import ModelDecision
from engineering_orchestrator.models import Task, TaskArtifact


class OpenCodeExecutor:
    def execute(
        self,
        task: Task,
        artifacts: list[TaskArtifact] | None = None,
        prompt_bundle: PromptBundle | None = None,
        model_decision: ModelDecision | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(status="skipped", changed_files=[], summary="OpenCodeExecutor is not implemented in the MVP.")
