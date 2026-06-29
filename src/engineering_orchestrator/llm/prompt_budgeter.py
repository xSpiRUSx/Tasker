from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

import yaml

from engineering_orchestrator.llm.prompt_bundle import PromptBundle
from engineering_orchestrator.llm.types import ContextManifest, PromptArtifactEntry
from engineering_orchestrator.models import Task, TaskArtifact


PROMPT_ARTIFACT_KINDS = {
    "request",
    "route_decision",
    "context_summary",
    "working_memory",
    "spec",
    "todo",
    "test_plan",
    "approval_request",
    "executor_policy",
    "repair_prompt",
    "correction_request",
    "correction_context",
    "context_compact",
}

MAX_PROMPT_ARTIFACT_CHARS = 40_000


class PromptBudgetError(ValueError):
    pass


class PromptBudgeter:
    def __init__(self, config_path: str | Path):
        self.path = Path(config_path)
        self.data = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.forbidden_patterns = [str(item) for item in self.data.get("forbidden_prompt_artifacts", [])]
        self.max_single_artifact_chars = int((self.data.get("global") or {}).get("max_single_artifact_chars") or MAX_PROMPT_ARTIFACT_CHARS)

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

    def build_bundle(
        self,
        task: Task,
        operation: str,
        artifacts: Iterable[TaskArtifact],
        artifacts_root: str | Path,
        run_id: str | None = None,
        model_decision_id: str | None = None,
    ) -> PromptBundle:
        root = Path(artifacts_root)
        included: list[PromptArtifactEntry] = []
        excluded: list[PromptArtifactEntry] = []
        artifact_sections: list[str] = []

        for artifact in self._latest_prompt_artifacts(artifacts):
            if self.is_forbidden(artifact):
                excluded.append(self._entry(artifact, 0, "forbidden_runtime_artifact"))
                continue
            path = root / artifact.relative_path
            if not path.exists():
                excluded.append(self._entry(artifact, 0, "missing_artifact"))
                continue
            content = path.read_text(encoding="utf-8")
            if len(content) > self.max_single_artifact_chars:
                content = (
                    content[: self.max_single_artifact_chars]
                    + "\n\n[Artifact truncated before sending to runtime. Open the file path above if more context is needed.]"
                )
            included.append(self._entry(artifact, len(content), None))
            artifact_sections.append(
                f"## Artifact: {artifact.title} ({artifact.kind})\n\n"
                f"Path: {path}\n\n"
                f"```markdown\n{content}\n```"
            )

        prompt = self._render_executor_prompt(task, artifact_sections, is_correction=operation == "execute_micro_correction")
        total = len(prompt)
        budget = self.max_chars(operation)
        status = "ok" if total <= budget else "prompt_too_large"
        return PromptBundle(
            task_id=task.id,
            run_id=run_id,
            operation=operation,
            prompt=prompt,
            total_chars=total,
            budget_chars=budget,
            included_artifacts=[entry.model_dump(mode="json") for entry in included],
            excluded_artifacts=[entry.model_dump(mode="json") for entry in excluded],
            model_decision_id=model_decision_id,
        )

    def ensure_bundle_within_budget(self, bundle: PromptBundle) -> None:
        if bundle.total_chars > bundle.budget_chars:
            raise PromptBudgetError(
                f"Prompt for `{bundle.operation}` is {bundle.total_chars} chars; budget is {bundle.budget_chars}."
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

    def _latest_prompt_artifacts(self, artifacts: Iterable[TaskArtifact]) -> list[TaskArtifact]:
        latest_by_kind: dict[str, TaskArtifact] = {}
        for artifact in artifacts:
            if artifact.kind not in PROMPT_ARTIFACT_KINDS:
                if self.is_forbidden(artifact):
                    latest_by_kind.setdefault(f"__excluded__{artifact.id}", artifact)
                continue
            current = latest_by_kind.get(artifact.kind)
            if current is None or self._artifact_sort_key(artifact) > self._artifact_sort_key(current):
                latest_by_kind[artifact.kind] = artifact
        return sorted(latest_by_kind.values(), key=lambda item: (item.kind, item.version or 0, item.created_at))

    def _artifact_sort_key(self, artifact: TaskArtifact) -> tuple[int, str]:
        return (artifact.version or 0, artifact.created_at.isoformat())

    def _render_executor_prompt(self, task: Task, artifact_sections: list[str], is_correction: bool) -> str:
        if is_correction:
            return f"""
You are applying a user-requested correction to an already reviewed diff.

Task ID: {task.id}
Project: {task.project_id} / {task.project_name}
Workflow: {task.workflow_id} / {task.workflow_name}
Risk: {task.risk_level}

Original user request:
{task.user_message}

Instructions:
- The user review comment is approval to execute this correction.
- Do not regenerate the full plan.
- Do not expand task scope.
- Only modify the current diff according to the correction comment.
- Do not touch unrelated files.
- Do not commit changes.
- Do not change secrets.
- Do not deploy.
- Respect any executor policy artifact below, including allowed paths, blocked paths, diff size, and changed-file limits.
- Run relevant local checks when they are obvious and safe.
- If the correction cannot be completed, leave clear notes in your final output.

Artifacts:

{chr(10).join(artifact_sections) if artifact_sections else "No readable correction artifacts were provided."}
""".strip()

        return f"""
You are Codex running inside an approved task worktree.

Task ID: {task.id}
Project: {task.project_id} / {task.project_name}
Workflow: {task.workflow_id} / {task.workflow_name}
Risk: {task.risk_level}

Original user request:
{task.user_message}

Instructions:
- Work only inside the current working directory.
- Implement the approved plan using the artifacts below.
- Do not commit changes.
- Do not change secrets.
- Do not deploy.
- Respect any executor policy artifact below, including allowed paths, blocked paths, diff size, and changed-file limits.
- Prefer small, focused changes.
- Run relevant local checks when they are obvious and safe.
- If the task cannot be completed, leave clear notes in your final output.

Artifacts:

{chr(10).join(artifact_sections) if artifact_sections else "No readable artifacts were provided."}
""".strip()
