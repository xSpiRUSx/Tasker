from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from engineering_orchestrator.llm.prompt_bundle import PromptBundle
from engineering_orchestrator.llm.types import ModelDecision
from engineering_orchestrator.models import Task, TaskArtifact


class ExecutionResult(BaseModel):
    status: Literal["success", "failed", "skipped"]
    changed_files: list[str] = Field(default_factory=list)
    summary: str
    logs: str = ""
    command: list[str] = Field(default_factory=list)
    prompt: str = ""
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class Executor(Protocol):
    def execute(
        self,
        task: Task,
        artifacts: list[TaskArtifact] | None = None,
        prompt_bundle: PromptBundle | None = None,
        model_decision: ModelDecision | None = None,
    ) -> ExecutionResult:
        ...
