from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class WorkflowRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"workflows": []}
        self.workflows: list[dict[str, Any]] = self.data.get("workflows", [])

    def select(self, intent: str, task_kind: str, complexity: str) -> dict[str, Any] | None:
        candidates = []
        for workflow in self.workflows:
            if workflow.get("id") == "clarify":
                continue
            if self._matches(workflow.get("intents", []), intent) and self._matches(workflow.get("task_kinds", []), task_kind):
                if self._matches(workflow.get("complexity", []), complexity):
                    candidates.append(workflow)
        if candidates:
            return candidates[0]
        return self.get("clarify")

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        return next((workflow for workflow in self.workflows if workflow.get("id") == workflow_id), None)

    def _matches(self, values: list[str], value: str) -> bool:
        return "*" in values or value in values
