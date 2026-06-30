from __future__ import annotations

import re
from dataclasses import dataclass


TYPE_MAPPING = {
    "external_report_or_processing": "feat",
    "1c_external_processing": "feat",
    "bugfix": "fix",
    "code_patch": "fix",
    "linked_correction": "fix",
    "correction": "fix",
    "docs": "docs",
    "docs_update": "docs",
    "config_change": "chore",
    "configuration_change": "chore",
    "refactor": "refactor",
    "test": "test",
    "test_update": "test",
    "feature": "feat",
}


@dataclass(frozen=True)
class CommitMessageInput:
    task_id: str
    project_id: str | None
    workflow_id: str | None
    task_kind: str | None
    normalized_task: str
    changed_files: list[str]
    validation_status: str


class CommitMessageBuilder:
    def build(self, data: CommitMessageInput) -> str:
        commit_type = self._type_for(data)
        scope = self._scope(data.project_id)
        subject = self._subject(data.normalized_task, data.task_id)
        bullets = data.changed_files[:5] or ["Prepared reviewed task changes."]
        body = "\n".join(f"- {item}" for item in bullets)
        return (
            f"{commit_type}({scope}): {subject}\n\n"
            f"Task: {data.task_id}\n\n"
            f"{body}\n\n"
            "Validation:\n"
            f"- {data.validation_status}"
        )

    def _type_for(self, data: CommitMessageInput) -> str:
        task_kind = (data.task_kind or "").strip()
        if data.workflow_id in {"simple_external_development", "1c_external_processing"}:
            return "feat"
        return TYPE_MAPPING.get(task_kind, "chore")

    def _scope(self, project_id: str | None) -> str:
        raw = project_id or "tasker"
        scope = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_").lower()
        return scope or "tasker"

    def _subject(self, text: str, task_id: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = re.sub(r"^(please|pls)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("-", " ")
        cleaned = cleaned.rstrip(".:;")
        if not cleaned:
            cleaned = task_id
        cleaned = cleaned[:1].lower() + cleaned[1:]
        if len(cleaned) <= 72:
            return cleaned
        return cleaned[:72].rstrip()
