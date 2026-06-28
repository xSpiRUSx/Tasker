from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from engineering_orchestrator.executors.base import ExecutionResult
from engineering_orchestrator.loop.evaluator import Evaluator, LoopEvaluation
from engineering_orchestrator.loop.observer import Observation, Observer
from engineering_orchestrator.loop.stop_conditions import LoopPolicy
from engineering_orchestrator.models import Task
from engineering_orchestrator.services.validation_service import ValidationResult


class LoopResult(BaseModel):
    status: str
    iterations: int
    execution_result: ExecutionResult
    validation_result: ValidationResult
    observation: Observation
    evaluation: LoopEvaluation


class LoopEngine:
    def __init__(
        self,
        observer: Observer | None = None,
        evaluator: Evaluator | None = None,
        policy: LoopPolicy | None = None,
    ):
        self.policy = policy or LoopPolicy()
        self.observer = observer or Observer()
        self.evaluator = evaluator or Evaluator(self.policy)

    def run(
        self,
        task: Task,
        execute: Callable[[], ExecutionResult],
        validate: Callable[[], ValidationResult],
        project: dict[str, Any] | None = None,
        workflow: dict[str, Any] | None = None,
        approved_gates: set[str] | None = None,
    ) -> LoopResult:
        execution_result = execute()
        validation_result = validate()
        observation = self.observer.observe(task.worktree_path, execution_result, validation_result)
        evaluation = self.evaluator.evaluate(observation, project, workflow, approved_gates)
        return LoopResult(
            status=evaluation.status,
            iterations=1,
            execution_result=execution_result,
            validation_result=validation_result,
            observation=observation,
            evaluation=evaluation,
        )
