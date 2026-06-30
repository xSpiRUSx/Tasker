from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from engineering_orchestrator.loop.observer import Observation
from engineering_orchestrator.loop.stop_conditions import LoopPolicy
from engineering_orchestrator.policies.evaluation_policy import EvaluationPolicy
from engineering_orchestrator.policies.file_policy import FilePolicy


class LoopEvaluation(BaseModel):
    passed: bool
    status: str
    findings: list[dict[str, Any]]


class Evaluator:
    def __init__(self, policy: LoopPolicy | None = None):
        self.policy = policy or LoopPolicy()
        self.evaluation_policy = EvaluationPolicy()

    def evaluate(
        self,
        observation: Observation,
        project: dict[str, Any] | None = None,
        workflow: dict[str, Any] | None = None,
        approved_gates: set[str] | None = None,
    ) -> LoopEvaluation:
        file_findings = FilePolicy(project, workflow).evaluate(observation.changed_files, approved_gates)
        validation_status = observation.validation_result.status
        if validation_status == "skipped" and getattr(observation.validation_result, "manual_review_required", False):
            validation_status = "manual_review_required"
        passed, status, findings = self.evaluation_policy.evaluate(
            executor_status=observation.executor_result.status,
            validation_status=validation_status,
            changed_files=observation.changed_files,
            diff_text=observation.diff_patch,
            file_findings=file_findings,
            max_changed_files=self.policy.max_changed_files,
            max_diff_lines=self.policy.max_diff_lines,
        )
        return LoopEvaluation(passed=passed, status=status, findings=findings)
