from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

import yaml

from engineering_orchestrator.llm.types import ContextManifest, PromptArtifactEntry
from engineering_orchestrator.models import TaskArtifact


class PromptBudgetError(ValueError):
    pass


class PromptBudgeter:
    def __init__(self, config_path: str | Path):
        self.path = Path(config_path)
        self.data = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.forbidden_patterns = [str(item) for item in self.data.get("forbidden_prompt_artifacts", [])]

    def max_chars(self, operation: str) -> int:
        operation_budgets = self.data.get("operation_budgets") or {}
        global_budget = self.data.get("global") or {}
        return int((operation_budgets.get(operation) or {}).get("max_prompt_chars") or global_budget.get("max_prompt_chars") or 300000)

    def build_manifest(
        self,
        operation: str,
        artifacts: Iterable[TaskArtifact],
        artifacts_root: str | Path,
        base_prompt_chars: int = 0,
    ) -> ContextManifest:
        root = Path(artifacts_root)
        included: list[PromptArtifactEntry] = []
        excluded: list[PromptArtifactEntry] = []
        total = base_prompt_chars
        budget = self.max_chars(operation)

        for artifact in artifacts:
            if self.is_forbidden(artifact):
                excluded.append(self._entry(artifact, 0, "forbidden_runtime_artifact"))
                continue
            path = root / artifact.relative_path
            chars = len(path.read_text(encoding="utf-8")) if path.exists() else 0
            total += chars
            included.append(self._entry(artifact, chars, None))

        status = "ok" if total <= budget else "prompt_too_large"
        return ContextManifest(
            operation=operation,
            included_artifacts=included,
            excluded_artifacts=excluded,
            total_chars=total,
            budget_chars=budget,
            status=status,
        )

    def ensure_within_budget(self, manifest: ContextManifest) -> None:
        if manifest.total_chars > manifest.budget_chars:
            raise PromptBudgetError(
                f"Prompt for `{manifest.operation}` is {manifest.total_chars} chars; budget is {manifest.budget_chars}."
            )

    def is_forbidden(self, artifact: TaskArtifact) -> bool:
        path = artifact.relative_path.replace("\\", "/")
        filename = Path(path).name
        return any(fnmatch(path, pattern) or fnmatch(filename, pattern) for pattern in self.forbidden_patterns)

    def _entry(self, artifact: TaskArtifact, chars: int, reason: str | None) -> PromptArtifactEntry:
        return PromptArtifactEntry(
            kind=artifact.kind,
            version=artifact.version,
            chars=chars,
            path=artifact.relative_path,
            reason=reason,
        )
